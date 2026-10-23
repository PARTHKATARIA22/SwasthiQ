"""
Unit tests for the SwasthiQ tool layer.

Covers:
  - Monday window overlap deduplication for dr_rao
  - Holiday (2026-10-02), Sunday (2026-10-04), leave dates
  - Ambiguous lookup for "Sharma" returning 3 candidates
  - Guardian lookup for Sunita Gupta and Meera Joshi
  - Double-booking rejection + multi-threaded race test
  - Reschedule, cancel, escalation flows
  - Error handling (invalid doctor, missing params, etc.)
"""

from __future__ import annotations

import threading
import unittest
from collections import Counter

from backend.store import ClinicStore
from backend.tools import Session


class TestSlotGeneration(unittest.TestCase):
    """Test that slot generation handles overlapping windows correctly."""

    def setUp(self):
        self.store = ClinicStore()

    def test_monday_dr_rao_dedup(self):
        """dr_rao has Mon 09:00-12:00 and Mon 11:45-15:00 → overlap at 11:45.
        After dedup, 11:45 should appear exactly once."""
        # 2026-10-05 is Monday
        slots = self.store.get_slots_for_day("dr_rao", "2026-10-05")
        self.assertEqual(slots.count("11:45"), 1)

        # Should start at 09:00
        self.assertEqual(slots[0], "09:00")
        # Should end at 14:45 (last 15-min slot fitting before 15:00)
        self.assertEqual(slots[-1], "14:45")

        # Total unique slots: 09:00-11:45 = 12 slots, then 12:00-14:45 = 12 slots = 24 total
        # Actually: 09:00,09:15,...,11:45 = 12 slots, then 12:00,...,14:45 = 12 more = 24
        expected = []
        h, m = 9, 0
        while h < 15 or (h == 14 and m <= 45):
            expected.append(f"{h:02d}:{m:02d}")
            m += 15
            if m == 60:
                m = 0
                h += 1
            if h == 15:
                break
        self.assertEqual(slots, expected)

    def test_monday_dr_rao_11_45_unique(self):
        """Verify that 11:45 appears once, confirming dedup."""
        slots = self.store.get_slots_for_day("dr_rao", "2026-10-05")
        count = Counter(slots)
        self.assertEqual(count["11:45"], 1)

    def test_saturday_dr_rao_slots(self):
        """Saturday: 09:00-13:00 → 16 slots (09:00..12:45)."""
        # 2026-10-03 is Saturday
        slots = self.store.get_slots_for_day("dr_rao", "2026-10-03")
        self.assertEqual(slots[0], "09:00")
        self.assertEqual(slots[-1], "12:45")
        self.assertEqual(len(slots), 16)

    def test_thursday_dr_rao_two_windows(self):
        """Thu: 09:00-12:00 and 16:00-19:00."""
        # 2026-10-01 is Thursday
        slots = self.store.get_slots_for_day("dr_rao", "2026-10-01")
        self.assertIn("09:00", slots)
        self.assertIn("11:45", slots)
        self.assertIn("16:00", slots)
        self.assertIn("18:45", slots)
        # No slots between 12:00 and 16:00
        self.assertNotIn("12:00", slots)
        self.assertNotIn("15:45", slots)


class TestHolidaysSundaysLeaves(unittest.TestCase):
    """Test search_slots for holidays, Sundays, and leave dates."""

    def setUp(self):
        self.session = Session()

    def test_holiday_2026_10_02(self):
        result = self.session.search_slots("dr_rao", "2026-10-02")
        self.assertEqual(result["status"], "closed")
        self.assertEqual(result["reason"], "clinic_holiday")
        self.assertEqual(result["available_slots"], [])

    def test_sunday_2026_10_04(self):
        """Sunday: no doctor has windows → no_schedule_on_day."""
        result = self.session.search_slots("dr_rao", "2026-10-04")
        self.assertEqual(result["status"], "closed")
        self.assertEqual(result["reason"], "no_schedule_on_day")

    def test_dr_sethi_leave_oct_5(self):
        result = self.session.search_slots("dr_sethi", "2026-10-05")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "doctor_on_leave")

    def test_dr_sethi_leave_oct_6(self):
        result = self.session.search_slots("dr_sethi", "2026-10-06")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "doctor_on_leave")

    def test_dr_sethi_leave_oct_7(self):
        result = self.session.search_slots("dr_sethi", "2026-10-07")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "doctor_on_leave")

    def test_dr_rao_leave_oct_9(self):
        result = self.session.search_slots("dr_rao", "2026-10-09")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "doctor_on_leave")

    def test_dr_rao_not_on_leave_oct_8(self):
        """dr_rao is NOT on leave on Oct 8 (Thu)."""
        result = self.session.search_slots("dr_rao", "2026-10-08")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(len(result["available_slots"]) > 0)


class TestSearchSlotsWindowFilter(unittest.TestCase):
    """Test window filtering (morning/afternoon/evening)."""

    def setUp(self):
        self.session = Session()

    def test_morning_filter(self):
        # 2026-10-03 Saturday, dr_rao 09:00-13:00
        result = self.session.search_slots("dr_rao", "2026-10-03", window="morning")
        self.assertEqual(result["status"], "ok")
        for slot in result["available_slots"]:
            self.assertLess(slot, "12:00")

    def test_afternoon_filter(self):
        result = self.session.search_slots("dr_rao", "2026-10-03", window="afternoon")
        self.assertEqual(result["status"], "ok")
        for slot in result["available_slots"]:
            self.assertGreaterEqual(slot, "12:00")
            self.assertLess(slot, "16:00")

    def test_evening_filter(self):
        # 2026-10-01 Thu: 16:00-19:00
        result = self.session.search_slots("dr_rao", "2026-10-01", window="evening")
        self.assertEqual(result["status"], "ok")
        for slot in result["available_slots"]:
            self.assertGreaterEqual(slot, "16:00")


class TestLookupPatient(unittest.TestCase):
    """Test patient lookup including ambiguous cases and guardian relationships."""

    def setUp(self):
        self.session = Session()

    def test_missing_params(self):
        result = self.session.lookup_patient()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "missing_params")

    def test_sharma_ambiguous_3_candidates(self):
        """Searching 'Sharma' returns 3 distinct Sharmas."""
        result = self.session.lookup_patient(name="Sharma")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["ambiguous"])
        ids = {c["id"] for c in result["candidates"]}
        self.assertIn("pt_0001", ids)  # Rajesh Kumar Sharma
        self.assertIn("pt_0002", ids)  # R. K. Sharma
        self.assertIn("pt_0003", ids)  # Rajesh Sharma
        self.assertEqual(len(ids), 3)

    def test_sharma_candidates_have_appointments(self):
        """Each Sharma candidate should have active_appointments populated."""
        result = self.session.lookup_patient(name="Sharma")
        for c in result["candidates"]:
            self.assertIn("active_appointments", c)

    def test_rajesh_kumar_sharma_with_phone(self):
        """Name+phone uniquely resolves to pt_0001."""
        result = self.session.lookup_patient(name="Rajesh Kumar Sharma", phone="9812200011")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["ambiguous"])
        self.assertEqual(result["candidates"][0]["id"], "pt_0001")

    def test_guardian_sunita_gupta(self):
        """Sunita Gupta (9812200166) is guardian of Aarav (pt_0006) and Arjun (pt_0007)."""
        result = self.session.lookup_patient(name="Sunita Gupta", phone="9812200166")
        self.assertEqual(result["status"], "ok")
        ids = {c["id"] for c in result["candidates"]}
        self.assertIn("pt_0008", ids)  # Sunita herself
        self.assertIn("pt_0006", ids)  # Aarav
        self.assertIn("pt_0007", ids)  # Arjun

    def test_guardian_meera_joshi(self):
        """Meera Joshi (9812200197) is guardian of Kabir (pt_0031)."""
        result = self.session.lookup_patient(name="Meera Joshi", phone="9812200197")
        self.assertEqual(result["status"], "ok")
        ids = {c["id"] for c in result["candidates"]}
        self.assertIn("pt_0009", ids)  # Meera
        self.assertIn("pt_0031", ids)  # Kabir

    def test_priya_nair_unique(self):
        """Priya Nair + phone → unique match (not Priya Menon)."""
        result = self.session.lookup_patient(name="Priya Nair", phone="9812200104")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["ambiguous"])
        self.assertEqual(result["candidates"][0]["id"], "pt_0004")

    def test_lakshmi_iyer_by_name(self):
        """Lakshmi Iyer by name → single match."""
        result = self.session.lookup_patient(name="Lakshmi Iyer")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["ambiguous"])
        self.assertEqual(result["candidates"][0]["id"], "pt_0012")

    def test_patient_id_lookup(self):
        result = self.session.lookup_patient(patient_id="pt_0013")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidates"][0]["name"], "Harpreet Singh")

    def test_phone_normalization(self):
        """Phone with +91 prefix should still match."""
        result = self.session.lookup_patient(phone="+91 9812200311")
        self.assertEqual(result["status"], "ok")
        ids = {c["id"] for c in result["candidates"]}
        self.assertIn("pt_0013", ids)

    def test_candidates_include_active_appointments(self):
        """cv_0003: Rajesh Kumar Sharma has ap_0001 on 2026-10-01 09:30."""
        result = self.session.lookup_patient(name="Rajesh Kumar Sharma", phone="9812200011")
        pt = result["candidates"][0]
        self.assertTrue(len(pt["active_appointments"]) > 0)
        appt_ids = {a["appointment_id"] for a in pt["active_appointments"]}
        self.assertIn("ap_0001", appt_ids)

    def test_candidates_include_authorised_guardians(self):
        """Aarav Gupta (pt_0006) should show Sunita Gupta as authorised guardian."""
        result = self.session.lookup_patient(patient_id="pt_0006")
        pt = result["candidates"][0]
        guardian_ids = {g["id"] for g in pt["authorised_guardians"]}
        self.assertIn("pt_0008", guardian_ids)


class TestBookAppointment(unittest.TestCase):
    """Test booking including double-booking rejection."""

    def setUp(self):
        self.session = Session()

    def test_simple_booking(self):
        """Book a free slot on Saturday 2026-10-03."""
        result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-03",
            start="09:00",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["appointment"]["patient_id"], "pt_0013")
        self.assertEqual(result["appointment"]["start"], "09:00")
        self.assertEqual(result["appointment"]["status"], "booked")

    def test_double_booking_rejection(self):
        """ap_0015 has dr_rao on 2026-10-08 at 09:00 → slot_taken."""
        result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-08",
            start="09:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "slot_taken")

    def test_booking_on_holiday(self):
        result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-02",
            start="09:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "clinic_holiday")

    def test_booking_on_sunday(self):
        result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-04",
            start="09:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "invalid_slot")

    def test_booking_doctor_on_leave(self):
        result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-09",
            start="09:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "doctor_on_leave")

    def test_booking_invalid_patient(self):
        result = self.session.book_appointment(
            patient_id="pt_9999",
            doctor_id="dr_rao",
            date="2026-10-03",
            start="09:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "patient_not_found")

    def test_guardian_authorised_booking(self):
        """Sunita (pt_0008) booking for Aarav (pt_0006) should succeed."""
        result = self.session.book_appointment(
            patient_id="pt_0006",
            doctor_id="dr_sethi",
            date="2026-10-08",
            start="17:00",
            caller_patient_id="pt_0008",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["appointment"]["patient_id"], "pt_0006")

    def test_guardian_not_authorised(self):
        """Mohit Negi (pt_0020) is NOT a guardian of Lakshmi Iyer (pt_0012)."""
        result = self.session.book_appointment(
            patient_id="pt_0012",
            doctor_id="dr_rao",
            date="2026-10-03",
            start="09:00",
            caller_patient_id="pt_0020",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "not_authorised")

    def test_appointment_id_format(self):
        """New appointments should get IDs like ap_0026, ap_0027, etc."""
        result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-03",
            start="09:00",
        )
        self.assertEqual(result["status"], "ok")
        # 25 existing appointments → first new one is ap_0026
        self.assertEqual(result["appointment"]["id"], "ap_0026")


class TestRescheduleAppointment(unittest.TestCase):
    """Test rescheduling flows."""

    def setUp(self):
        self.session = Session()

    def test_reschedule_success(self):
        """Reschedule ap_0001 (pt_0001, dr_rao, 2026-10-01 09:30) to Sat 10:00."""
        result = self.session.reschedule_appointment(
            appointment_id="ap_0001",
            new_date="2026-10-03",
            new_start="10:00",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["appointment"]["date"], "2026-10-03")
        self.assertEqual(result["appointment"]["start"], "10:00")

    def test_reschedule_to_taken_slot(self):
        """Reschedule to a slot that's already booked should fail."""
        result = self.session.reschedule_appointment(
            appointment_id="ap_0001",
            new_date="2026-10-08",
            new_start="09:00",  # Taken by ap_0015
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "slot_taken")

    def test_reschedule_nonexistent(self):
        result = self.session.reschedule_appointment(
            appointment_id="ap_9999",
            new_date="2026-10-03",
            new_start="10:00",
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "appointment_not_found")

    def test_reschedule_with_doctor_change(self):
        """Reschedule ap_0001 from dr_rao to dr_sethi on 2026-10-03 (Sat)."""
        result = self.session.reschedule_appointment(
            appointment_id="ap_0001",
            new_date="2026-10-03",
            new_start="10:00",
            new_doctor_id="dr_sethi",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["appointment"]["doctor_id"], "dr_sethi")


class TestCancelAppointment(unittest.TestCase):
    """Test cancellation flows."""

    def setUp(self):
        self.session = Session()

    def test_cancel_success(self):
        """Cancel ap_0002 (Priya Nair on 2026-10-01)."""
        result = self.session.cancel_appointment("ap_0002")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["appointment"]["status"], "cancelled")

    def test_cancel_already_cancelled(self):
        """Cancel twice should fail the second time."""
        self.session.cancel_appointment("ap_0002")
        result = self.session.cancel_appointment("ap_0002")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "not_booked")

    def test_cancel_nonexistent(self):
        result = self.session.cancel_appointment("ap_9999")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "appointment_not_found")

    def test_cancel_with_authorisation(self):
        """Priya Nair (pt_0004) cancels her own ap_0002."""
        result = self.session.cancel_appointment("ap_0002", caller_patient_id="pt_0004")
        self.assertEqual(result["status"], "ok")

    def test_cancel_not_authorised(self):
        """Random patient trying to cancel someone else's appointment."""
        result = self.session.cancel_appointment("ap_0002", caller_patient_id="pt_0020")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "not_authorised")


class TestEscalateToHuman(unittest.TestCase):
    """Test escalation including clinical_urgent rollback."""

    def setUp(self):
        self.session = Session()

    def test_valid_escalation(self):
        result = self.session.escalate_to_human(reason="medical_advice", detail="Fever dosage query")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["escalated"])
        self.assertEqual(self.session.terminal_state, "escalated")
        self.assertEqual(self.session.escalation_reason, "medical_advice")

    def test_invalid_reason(self):
        result = self.session.escalate_to_human(reason="not_a_real_reason")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["code"], "invalid_reason")

    def test_clinical_urgent_rollback(self):
        """If a booking was made then clinical_urgent escalation fires,
        the booked appointment should be cancelled."""
        # Book an appointment first
        book_result = self.session.book_appointment(
            patient_id="pt_0013",
            doctor_id="dr_rao",
            date="2026-10-03",
            start="09:00",
        )
        self.assertEqual(book_result["status"], "ok")
        appt_id = book_result["appointment"]["id"]

        # Now escalate as clinical_urgent
        esc_result = self.session.escalate_to_human(reason="clinical_urgent", detail="Chest pain")
        self.assertEqual(esc_result["status"], "ok")

        # The appointment should be cancelled
        appt = self.session.store.get_appointment(appt_id)
        self.assertEqual(appt["status"], "cancelled")


class TestDoctorIdNormalization(unittest.TestCase):
    """Test that obvious doctor_id variants are accepted."""

    def setUp(self):
        self.store = ClinicStore()

    def test_canonical_ids(self):
        self.assertEqual(self.store.normalize_doctor_id("dr_rao"), "dr_rao")
        self.assertEqual(self.store.normalize_doctor_id("dr_sethi"), "dr_sethi")

    def test_d_rao_variant(self):
        self.assertEqual(self.store.normalize_doctor_id("d_rao"), "dr_rao")

    def test_dr_dot_rao_variant(self):
        self.assertEqual(self.store.normalize_doctor_id("Dr. Rao"), "dr_rao")

    def test_invalid_doctor(self):
        self.assertIsNone(self.store.normalize_doctor_id("dr_nobody"))


class TestToolCallRecording(unittest.TestCase):
    """Verify that every call (including errors) is recorded."""

    def setUp(self):
        self.session = Session()

    def test_calls_recorded(self):
        self.session.search_slots("dr_rao", "2026-10-03")
        self.session.lookup_patient(name="Sharma")
        self.session.book_appointment("pt_9999", "dr_rao", "2026-10-03", "09:00")
        self.assertEqual(len(self.session.tool_calls), 3)
        self.assertEqual(self.session.tool_calls[0]["name"], "search_slots")
        self.assertEqual(self.session.tool_calls[1]["name"], "lookup_patient")
        self.assertEqual(self.session.tool_calls[2]["name"], "book_appointment")

    def test_failed_calls_recorded(self):
        self.session.search_slots("dr_nobody", "2026-10-03")
        self.assertEqual(len(self.session.tool_calls), 1)
        self.assertEqual(self.session.tool_calls[0]["name"], "search_slots")


class TestConcurrencyRace(unittest.TestCase):
    """5 threads simultaneously try to book the exact same open slot.
    Exactly 1 must succeed and 4 must get slot_taken."""

    def test_concurrent_double_booking(self):
        # Use a SHARED store so all threads see the same state
        shared_store = ClinicStore()

        results = []
        lock = threading.Lock()

        def try_book(thread_id: int):
            # Each thread gets its own Session but shares the store
            session = Session(store=shared_store)
            result = session.book_appointment(
                patient_id=f"pt_{thread_id + 1:04d}",
                doctor_id="dr_rao",
                date="2026-10-03",
                start="10:00",
            )
            with lock:
                results.append(result)

        threads = [threading.Thread(target=try_book, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r["status"] == "ok"]
        failures = [r for r in results if r["status"] == "error" and r["code"] == "slot_taken"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {len(successes)}")
        self.assertEqual(len(failures), 4, f"Expected exactly 4 slot_taken, got {len(failures)}")


class TestExistingBookedSlotsExcluded(unittest.TestCase):
    """Test that search_slots excludes already-booked slots."""

    def setUp(self):
        self.session = Session()

    def test_oct_08_0900_excluded(self):
        """ap_0015 books dr_rao on 2026-10-08 at 09:00 → should be excluded."""
        result = self.session.search_slots("dr_rao", "2026-10-08")
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("09:00", result["available_slots"])
        # 16:00 is also booked (ap_0016)
        self.assertNotIn("16:00", result["available_slots"])
        # 16:15 is also booked (ap_0017)
        self.assertNotIn("16:15", result["available_slots"])


if __name__ == "__main__":
    unittest.main()
