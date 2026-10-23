"""
The six deterministic tools for the SwasthiQ Clinic Front Desk Agent.

Every tool returns a structured dict.  Errors are returned as
{"status": "error", "code": "...", "error": "..."} — never raised as exceptions.

Each tool call (including failures) is recorded in session.tool_calls
in the format {"name": tool_name, "arguments": args_dict}.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .store import ClinicStore

# Valid escalation reasons
VALID_ESCALATION_REASONS = {
    "clinical_urgent",
    "medical_advice",
    "not_authorised",
    "ambiguous_patient",
    "out_of_scope",
}

# Window filter boundaries
_WINDOW_FILTERS = {
    "morning":   lambda s: s < "12:00",
    "afternoon": lambda s: "12:00" <= s < "16:00",
    "evening":   lambda s: s >= "16:00",
}


class Session:
    """
    Per-conversation session that wraps a ClinicStore and records tool calls.

    Create one per POST /agent/run.  Pass an existing ClinicStore if you need
    shared-mode concurrency (e.g. for race-condition tests); otherwise a fresh
    store is created from clinic.json.
    """

    def __init__(self, store: ClinicStore | None = None, clinic_path: str | None = None):
        self.store = store or ClinicStore(clinic_path=clinic_path)
        self.tool_calls: List[Dict[str, Any]] = []
        self.terminal_state: str | None = None
        self.escalation_reason: str | None = None
        # Track appointment IDs created during *this* session (for rollback on clinical_urgent)
        self._created_appt_ids: List[str] = []

    # ------------------------------------------------------------------
    # Internal: record every call
    # ------------------------------------------------------------------
    def _record(self, name: str, arguments: dict) -> None:
        self.tool_calls.append({"name": name, "arguments": arguments})

    # ------------------------------------------------------------------
    # 1. search_slots
    # ------------------------------------------------------------------
    def search_slots(
        self,
        doctor_id: str,
        date: str,
        window: str | None = None,
    ) -> dict:
        args = {"doctor_id": doctor_id, "date": date}
        if window is not None:
            args["window"] = window
        self._record("search_slots", args)

        # Validate doctor_id
        canonical = self.store.normalize_doctor_id(doctor_id)
        if canonical is None:
            return {
                "status": "error",
                "code": "invalid_doctor",
                "error": f"Unknown doctor_id: {doctor_id!r}. Valid IDs: {sorted(self.store.doctors.keys())}",
            }
        doctor_id = canonical

        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {
                "status": "error",
                "code": "invalid_date",
                "error": f"Date must be YYYY-MM-DD, got: {date!r}",
            }

        # Holiday check
        if self.store.is_holiday(date):
            return {
                "status": "closed",
                "reason": "clinic_holiday",
                "doctor_id": doctor_id,
                "date": date,
                "available_slots": [],
            }

        # Doctor on leave
        if self.store.is_on_leave(doctor_id, date):
            return {
                "status": "unavailable",
                "reason": "doctor_on_leave",
                "doctor_id": doctor_id,
                "date": date,
                "available_slots": [],
            }

        # Check weekday has windows
        all_day_slots = self.store.get_slots_for_day(doctor_id, date)
        if not all_day_slots:
            return {
                "status": "closed",
                "reason": "no_schedule_on_day",
                "doctor_id": doctor_id,
                "date": date,
                "available_slots": [],
            }

        # Filter out booked slots
        available = self.store.get_available_slots(doctor_id, date)

        # Window filter
        if window is not None:
            wl = window.strip().lower()
            filt = _WINDOW_FILTERS.get(wl)
            if filt is None:
                return {
                    "status": "error",
                    "code": "invalid_window",
                    "error": f"window must be one of 'morning', 'afternoon', 'evening'; got {window!r}",
                }
            window_slots = [s for s in available if filt(s)]
            return {
                "status": "ok",
                "doctor_id": doctor_id,
                "date": date,
                "window": wl,
                "available_slots": window_slots,
                "all_day_slots": available,
                "earliest_slot": window_slots[0] if window_slots else (available[0] if available else None),
            }

        return {
            "status": "ok",
            "doctor_id": doctor_id,
            "date": date,
            "available_slots": available,
            "earliest_slot": available[0] if available else None,
        }

    # ------------------------------------------------------------------
    # 2. lookup_patient
    # ------------------------------------------------------------------
    def lookup_patient(
        self,
        name: str | None = None,
        phone: str | None = None,
        patient_id: str | None = None,
    ) -> dict:
        args: dict = {}
        if name is not None:
            args["name"] = name
        if phone is not None:
            args["phone"] = phone
        if patient_id is not None:
            args["patient_id"] = patient_id
        self._record("lookup_patient", args)

        # Must have at least one parameter
        if name is None and phone is None and patient_id is None:
            return {
                "status": "error",
                "code": "missing_params",
                "error": "At least one of name, phone, or patient_id must be provided.",
            }

        # Direct patient_id lookup
        if patient_id is not None:
            patient = self.store.patients.get(patient_id)
            if patient is None:
                return {
                    "status": "error",
                    "code": "patient_not_found",
                    "error": f"No patient with id {patient_id!r}.",
                }
            enriched = self._enrich_patient(patient)
            return {
                "status": "ok",
                "candidates": [enriched],
                "ambiguous": False,
            }

        # Phone + name provided: find by phone first, then resolve family/guardians
        if phone is not None and name is not None:
            phone_matches = self.store.find_patients_by_phone(phone)
            name_matches_on_phone = [p for p in phone_matches if self._name_matches(name, p["name"])]

            # Also look for a child: caller gives their own name + phone,
            # but the appointment is for a ward
            candidates = []
            seen_ids = set()

            # Add direct phone+name matches
            for p in name_matches_on_phone:
                if p["id"] not in seen_ids:
                    candidates.append(p)
                    seen_ids.add(p["id"])

            # If no direct match, try: caller name matches someone on this phone,
            # OR we look for wards linked to people on this phone
            if not candidates:
                # Maybe the name matches a ward of someone on this phone
                for p in phone_matches:
                    if p["id"] not in seen_ids:
                        candidates.append(p)
                        seen_ids.add(p["id"])

            # Expand: for each candidate, also include their wards and guardians
            family_ids: set = set()
            for c in candidates:
                for ward_id in c.get("guardian_of", []):
                    family_ids.add(ward_id)
                # Also check if any of the candidates' guardians are in the set
                for gid in self.store._guardian_reverse.get(c["id"], []):
                    family_ids.add(gid)

            # Add ward/family members not yet in candidates
            for fid in family_ids:
                if fid not in seen_ids and fid in self.store.patients:
                    candidates.append(self.store.patients[fid])
                    seen_ids.add(fid)

            enriched_candidates = [self._enrich_patient(c) for c in candidates]

            # Mark each with is_guardian_for
            for ec in enriched_candidates:
                p = self.store.patients[ec["id"]]
                ec["is_guardian_for"] = p.get("guardian_of", [])

            return {
                "status": "ok",
                "candidates": enriched_candidates,
                "ambiguous": len(enriched_candidates) > 1 and len(name_matches_on_phone) != 1,
            }

        if phone is not None:
            phone_matches = self.store.find_patients_by_phone(phone)
            if not phone_matches:
                return {
                    "status": "ok",
                    "candidates": [],
                    "ambiguous": False,
                }

            candidates = list(phone_matches)
            seen_ids = {p["id"] for p in candidates}

            # Expand family
            for p in phone_matches:
                for ward_id in p.get("guardian_of", []):
                    if ward_id not in seen_ids and ward_id in self.store.patients:
                        candidates.append(self.store.patients[ward_id])
                        seen_ids.add(ward_id)
                for gid in self.store._guardian_reverse.get(p["id"], []):
                    if gid not in seen_ids and gid in self.store.patients:
                        candidates.append(self.store.patients[gid])
                        seen_ids.add(gid)

            enriched_candidates = [self._enrich_patient(c) for c in candidates]
            for ec in enriched_candidates:
                p = self.store.patients[ec["id"]]
                ec["is_guardian_for"] = p.get("guardian_of", [])

            return {
                "status": "ok",
                "candidates": enriched_candidates,
                "ambiguous": len(enriched_candidates) > 1,
            }

        # Name only
        if name is not None:
            name_matches = self.store.find_patients_by_name(name)
            enriched_candidates = [self._enrich_patient(p) for p in name_matches]
            for ec in enriched_candidates:
                p = self.store.patients[ec["id"]]
                ec["is_guardian_for"] = p.get("guardian_of", [])

            return {
                "status": "ok",
                "candidates": enriched_candidates,
                "ambiguous": len(enriched_candidates) > 1,
            }

        # Should not reach here
        return {"status": "error", "code": "internal", "error": "Unexpected state."}

    def _name_matches(self, query: str, full_name: str) -> bool:
        """Case-insensitive token/substring match."""
        q = query.strip().lower()
        fn = full_name.lower()
        return all(tok in fn for tok in q.split())

    def _enrich_patient(self, patient: dict) -> dict:
        """Add active_appointments and authorised_guardians to a patient dict."""
        pid = patient["id"]
        return {
            "id": pid,
            "name": patient["name"],
            "phone": patient.get("phone", ""),
            "dob": patient.get("dob", ""),
            "guardian_of": patient.get("guardian_of", []),
            "active_appointments": self.store.get_active_appointments(pid),
            "authorised_guardians": self.store.get_authorised_guardians(pid),
        }

    # ------------------------------------------------------------------
    # 3. book_appointment
    # ------------------------------------------------------------------
    def book_appointment(
        self,
        patient_id: str,
        doctor_id: str,
        date: str,
        start: str,
        caller_patient_id: str | None = None,
    ) -> dict:
        args: dict = {
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "date": date,
            "start": start,
        }
        if caller_patient_id is not None:
            args["caller_patient_id"] = caller_patient_id
        self._record("book_appointment", args)

        # Validate patient exists
        if patient_id not in self.store.patients:
            return {
                "status": "error",
                "code": "patient_not_found",
                "error": f"No patient with id {patient_id!r}.",
            }

        # Guardian authorisation check
        if caller_patient_id is not None and caller_patient_id != patient_id:
            if not self.store.is_guardian_of(caller_patient_id, patient_id):
                return {
                    "status": "error",
                    "code": "not_authorised",
                    "error": "Caller is not an authorised guardian for this patient.",
                }

        # Validate doctor
        canonical_doc = self.store.normalize_doctor_id(doctor_id)
        if canonical_doc is None:
            return {
                "status": "error",
                "code": "invalid_doctor",
                "error": f"Unknown doctor_id: {doctor_id!r}.",
            }
        doctor_id = canonical_doc

        # Validate date
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {
                "status": "error",
                "code": "invalid_date",
                "error": f"Date must be YYYY-MM-DD, got: {date!r}.",
            }

        # Holiday
        if self.store.is_holiday(date):
            return {
                "status": "error",
                "code": "clinic_holiday",
                "error": f"The clinic is closed on {date} (holiday).",
            }

        # Leave
        if self.store.is_on_leave(doctor_id, date):
            return {
                "status": "error",
                "code": "doctor_on_leave",
                "error": f"Doctor {doctor_id} is on leave on {date}.",
            }

        # Validate start time format
        if not re.match(r"^\d{2}:\d{2}$", start):
            return {
                "status": "error",
                "code": "invalid_time",
                "error": f"start must be HH:MM, got: {start!r}.",
            }

        # Validate slot is within doctor's windows
        if not self.store.is_slot_in_windows(doctor_id, date, start):
            return {
                "status": "error",
                "code": "invalid_slot",
                "error": f"Slot {start} is not a valid slot for {doctor_id} on {date}.",
            }

        # Acquire lock for the actual booking
        with self.store.lock:
            # Double-check under lock: is the slot still free?
            booked = self.store.get_booked_slots(doctor_id, date)
            if start in booked:
                return {
                    "status": "error",
                    "code": "slot_taken",
                    "error": f"Slot {start} on {date} with {doctor_id} is already booked.",
                }

            appt_id = self.store._next_appointment_id()
            end = self.store.compute_end_time(start)
            appt = {
                "id": appt_id,
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "date": date,
                "start": start,
                "end": end,
                "status": "booked",
            }
            self.store._add_appointment(appt)
            self._created_appt_ids.append(appt_id)

        return {
            "status": "ok",
            "appointment": appt,
        }

    # ------------------------------------------------------------------
    # 4. reschedule_appointment
    # ------------------------------------------------------------------
    def reschedule_appointment(
        self,
        appointment_id: str,
        new_date: str,
        new_start: str,
        new_doctor_id: str | None = None,
        caller_patient_id: str | None = None,
    ) -> dict:
        args: dict = {
            "appointment_id": appointment_id,
            "new_date": new_date,
            "new_start": new_start,
        }
        if new_doctor_id is not None:
            args["new_doctor_id"] = new_doctor_id
        if caller_patient_id is not None:
            args["caller_patient_id"] = caller_patient_id
        self._record("reschedule_appointment", args)

        # Validate appointment exists
        appt = self.store.get_appointment(appointment_id)
        if appt is None:
            return {
                "status": "error",
                "code": "appointment_not_found",
                "error": f"No appointment with id {appointment_id!r}.",
            }

        if appt["status"] != "booked":
            return {
                "status": "error",
                "code": "not_booked",
                "error": f"Appointment {appointment_id} is not currently booked (status: {appt['status']}).",
            }

        # Authorisation
        if caller_patient_id is not None:
            if caller_patient_id != appt["patient_id"]:
                if not self.store.is_guardian_of(caller_patient_id, appt["patient_id"]):
                    return {
                        "status": "error",
                        "code": "not_authorised",
                        "error": "Caller is not authorised to modify this appointment.",
                    }

        target_doctor = new_doctor_id if new_doctor_id else appt["doctor_id"]

        # Validate doctor
        canonical_doc = self.store.normalize_doctor_id(target_doctor)
        if canonical_doc is None:
            return {
                "status": "error",
                "code": "invalid_doctor",
                "error": f"Unknown doctor_id: {target_doctor!r}.",
            }
        target_doctor = canonical_doc

        # Validate date
        try:
            datetime.strptime(new_date, "%Y-%m-%d")
        except ValueError:
            return {
                "status": "error",
                "code": "invalid_date",
                "error": f"Date must be YYYY-MM-DD, got: {new_date!r}.",
            }

        # Holiday
        if self.store.is_holiday(new_date):
            return {
                "status": "error",
                "code": "clinic_holiday",
                "error": f"The clinic is closed on {new_date} (holiday).",
            }

        # Leave
        if self.store.is_on_leave(target_doctor, new_date):
            return {
                "status": "error",
                "code": "doctor_on_leave",
                "error": f"Doctor {target_doctor} is on leave on {new_date}.",
            }

        # Validate time format
        if not re.match(r"^\d{2}:\d{2}$", new_start):
            return {
                "status": "error",
                "code": "invalid_time",
                "error": f"new_start must be HH:MM, got: {new_start!r}.",
            }

        # Validate slot
        if not self.store.is_slot_in_windows(target_doctor, new_date, new_start):
            return {
                "status": "error",
                "code": "invalid_slot",
                "error": f"Slot {new_start} is not a valid slot for {target_doctor} on {new_date}.",
            }

        with self.store.lock:
            # Check slot is free (excluding this appointment's own current slot
            # if moving within the same doctor/date)
            booked = self.store.get_booked_slots(target_doctor, new_date)
            # If rescheduling within same doctor+date, the old slot is still "booked" –
            # we should exclude it from the conflict check only if it's the SAME appt
            if (appt["doctor_id"] == target_doctor and appt["date"] == new_date
                    and appt["start"] in booked):
                booked = booked - {appt["start"]}

            if new_start in booked:
                return {
                    "status": "error",
                    "code": "slot_taken",
                    "error": f"Slot {new_start} on {new_date} with {target_doctor} is already booked.",
                }

            # Perform the reschedule
            appt["doctor_id"] = target_doctor
            appt["date"] = new_date
            appt["start"] = new_start
            appt["end"] = self.store.compute_end_time(new_start)

        return {
            "status": "ok",
            "appointment": dict(appt),
        }

    # ------------------------------------------------------------------
    # 5. cancel_appointment
    # ------------------------------------------------------------------
    def cancel_appointment(
        self,
        appointment_id: str,
        caller_patient_id: str | None = None,
    ) -> dict:
        args: dict = {"appointment_id": appointment_id}
        if caller_patient_id is not None:
            args["caller_patient_id"] = caller_patient_id
        self._record("cancel_appointment", args)

        appt = self.store.get_appointment(appointment_id)
        if appt is None:
            return {
                "status": "error",
                "code": "appointment_not_found",
                "error": f"No appointment with id {appointment_id!r}.",
            }

        if appt["status"] != "booked":
            return {
                "status": "error",
                "code": "not_booked",
                "error": f"Appointment {appointment_id} is not currently booked (status: {appt['status']}).",
            }

        # Authorisation
        if caller_patient_id is not None:
            if caller_patient_id != appt["patient_id"]:
                if not self.store.is_guardian_of(caller_patient_id, appt["patient_id"]):
                    return {
                        "status": "error",
                        "code": "not_authorised",
                        "error": "Caller is not authorised to cancel this appointment.",
                    }

        with self.store.lock:
            appt["status"] = "cancelled"

        return {
            "status": "ok",
            "appointment": dict(appt),
        }

    # ------------------------------------------------------------------
    # 6. escalate_to_human
    # ------------------------------------------------------------------
    def escalate_to_human(
        self,
        reason: str,
        detail: str = "",
        patient_id: str | None = None,
    ) -> dict:
        args: dict = {"reason": reason}
        if detail:
            args["detail"] = detail
        if patient_id is not None:
            args["patient_id"] = patient_id
        self._record("escalate_to_human", args)

        if reason not in VALID_ESCALATION_REASONS:
            return {
                "status": "error",
                "code": "invalid_reason",
                "error": (
                    f"reason must be one of {sorted(VALID_ESCALATION_REASONS)}; "
                    f"got {reason!r}"
                ),
            }

        # clinical_urgent: roll back any appointments created in this session
        if reason == "clinical_urgent":
            with self.store.lock:
                for appt_id in self._created_appt_ids:
                    appt = self.store.get_appointment(appt_id)
                    if appt and appt["status"] == "booked":
                        appt["status"] = "cancelled"
            self._created_appt_ids.clear()

        self.terminal_state = "escalated"
        self.escalation_reason = reason

        return {
            "status": "ok",
            "escalated": True,
            "reason": reason,
            "detail": detail,
            "patient_id": patient_id,
        }
