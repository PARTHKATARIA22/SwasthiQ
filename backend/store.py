"""
State management for the SwasthiQ Clinic Front Desk Agent.

Loads clinic.json fresh per conversation session and provides thread-safe
access to doctors, patients, appointments, holidays, and slot generation.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Default path to clinic.json – one directory above backend/
_DEFAULT_CLINIC_PATH = Path(__file__).resolve().parent.parent / "clinic.json"

# Map Python weekday int (0=Mon) to 3-letter abbreviation used in clinic.json
_WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ClinicStore:
    """
    Thread-safe, per-session state manager.

    On instantiation it deep-copies the raw clinic data so that each session
    starts from the original clinic.json state.  All mutation methods (book,
    reschedule, cancel) are protected by a threading.Lock.
    """

    def __init__(self, clinic_path: str | Path | None = None, raw_data: dict | None = None):
        """
        Parameters
        ----------
        clinic_path : path to clinic.json (defaults to repo-level clinic.json)
        raw_data    : if provided, use this dict directly instead of loading
                      from disk (useful for tests and shared-mode concurrency).
        """
        if raw_data is not None:
            data = copy.deepcopy(raw_data)
        else:
            path = Path(clinic_path) if clinic_path else _DEFAULT_CLINIC_PATH
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

        self.clinic: dict = data["clinic"]
        self.slot_minutes: int = self.clinic.get("slot_minutes", 15)

        # Index doctors by id
        self.doctors: Dict[str, dict] = {d["id"]: d for d in data["doctors"]}

        # Index patients by id
        self.patients: Dict[str, dict] = {p["id"]: p for p in data["patients"]}

        # Build reverse-index: phone -> list of patient ids
        self._phone_index: Dict[str, List[str]] = {}
        for pid, p in self.patients.items():
            norm = self._normalize_phone(p.get("phone", ""))
            self._phone_index.setdefault(norm, []).append(pid)

        # Build reverse guardian index: child_id -> list of guardian patient ids
        self._guardian_reverse: Dict[str, List[str]] = {}
        for pid, p in self.patients.items():
            for ward_id in p.get("guardian_of", []):
                self._guardian_reverse.setdefault(ward_id, []).append(pid)

        # Appointments list (mutable during session)
        self.appointments: List[dict] = copy.deepcopy(data.get("appointments", []))

        # Index appointments by id for O(1) lookup
        self._appt_index: Dict[str, dict] = {a["id"]: a for a in self.appointments}

        # Holidays set
        self.holidays: Set[str] = set(data.get("holidays", []))

        # Lock for all mutation operations
        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    # Phone normalisation
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Strip +91, spaces, hyphens from a phone string."""
        s = phone.strip()
        s = re.sub(r"[\s\-]", "", s)
        if s.startswith("+91"):
            s = s[3:]
        elif s.startswith("91") and len(s) == 12:
            s = s[2:]
        return s

    # ------------------------------------------------------------------
    # Doctor ID normalisation
    # ------------------------------------------------------------------
    def normalize_doctor_id(self, raw: str) -> str | None:
        """
        Accept canonical IDs and obvious variants. Returns canonical ID or None.
        """
        if raw in self.doctors:
            return raw

        # Lowercase, strip punctuation/spaces
        cleaned = re.sub(r"[.\s]+", "_", raw.strip().lower())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")

        # Map common variants
        aliases: Dict[str, str] = {}
        for doc_id, doc in self.doctors.items():
            aliases[doc_id] = doc_id
            # "dr_rao" aliases
            name_parts = doc["name"].lower().replace(".", "").split()
            # e.g. "dr anjali rao" -> dr_rao, d_rao, dr_anjali_rao
            if len(name_parts) >= 2:
                aliases["_".join(name_parts)] = doc_id                     # dr_anjali_rao
                aliases[name_parts[0] + "_" + name_parts[-1]] = doc_id     # dr_rao
                aliases[name_parts[-1]] = doc_id                            # rao
                # d_ variant
                if name_parts[0] in ("dr", "doctor"):
                    aliases["d_" + name_parts[-1]] = doc_id                 # d_rao

        return aliases.get(cleaned)

    # ------------------------------------------------------------------
    # Slot generation
    # ------------------------------------------------------------------
    def get_slots_for_day(self, doctor_id: str, date_str: str) -> List[str]:
        """
        Compute all valid 15-minute start times for a doctor on a given date.
        Deduplicates and sorts to fix overlapping windows (e.g. dr_rao Mon).
        Does NOT filter by existing bookings.
        """
        doc = self.doctors.get(doctor_id)
        if doc is None:
            return []

        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_abbr = _WEEKDAY_ABBR[dt.weekday()]

        slot_set: set = set()
        for window in doc.get("windows", []):
            if window["day"] != day_abbr:
                continue
            start_t = datetime.strptime(window["start"], "%H:%M")
            end_t = datetime.strptime(window["end"], "%H:%M")
            current = start_t
            while current + timedelta(minutes=self.slot_minutes) <= end_t:
                slot_set.add(current.strftime("%H:%M"))
                current += timedelta(minutes=self.slot_minutes)

        return sorted(slot_set)

    def is_slot_in_windows(self, doctor_id: str, date_str: str, start: str) -> bool:
        """Check if a given start time is a valid window slot for that doctor/day."""
        return start in self.get_slots_for_day(doctor_id, date_str)

    # ------------------------------------------------------------------
    # Booking queries (lock-free read helpers)
    # ------------------------------------------------------------------
    def is_holiday(self, date_str: str) -> bool:
        return date_str in self.holidays

    def is_on_leave(self, doctor_id: str, date_str: str) -> bool:
        doc = self.doctors.get(doctor_id)
        if doc is None:
            return False
        return date_str in doc.get("leave_dates", [])

    def get_booked_slots(self, doctor_id: str, date_str: str) -> Set[str]:
        """Return set of start times that are already booked for (doctor, date)."""
        booked: set = set()
        for appt in self.appointments:
            if (appt["doctor_id"] == doctor_id
                    and appt["date"] == date_str
                    and appt["status"] == "booked"):
                booked.add(appt["start"])
        return booked

    def get_available_slots(self, doctor_id: str, date_str: str) -> List[str]:
        """All slots minus already-booked ones."""
        all_slots = self.get_slots_for_day(doctor_id, date_str)
        booked = self.get_booked_slots(doctor_id, date_str)
        return [s for s in all_slots if s not in booked]

    # ------------------------------------------------------------------
    # Patient lookup helpers
    # ------------------------------------------------------------------
    def find_patients_by_phone(self, phone: str) -> List[dict]:
        norm = self._normalize_phone(phone)
        pids = self._phone_index.get(norm, [])
        return [self.patients[pid] for pid in pids]

    def find_patients_by_name(self, name: str) -> List[dict]:
        """Case-insensitive token/substring match across patient names."""
        name_lower = name.strip().lower()
        results = []
        for pid, p in self.patients.items():
            patient_name_lower = p["name"].lower()
            # Check if every token in the query appears as a substring in the patient name
            tokens = name_lower.split()
            if all(tok in patient_name_lower for tok in tokens):
                results.append(p)
        return results

    def get_active_appointments(self, patient_id: str) -> List[dict]:
        """Return list of booked appointments for a patient."""
        return [
            {
                "appointment_id": a["id"],
                "doctor_id": a["doctor_id"],
                "date": a["date"],
                "start": a["start"],
                "end": a["end"],
                "status": a["status"],
            }
            for a in self.appointments
            if a["patient_id"] == patient_id and a["status"] == "booked"
        ]

    def get_authorised_guardians(self, patient_id: str) -> List[dict]:
        """Return list of guardians who have this patient in their guardian_of."""
        guardian_ids = self._guardian_reverse.get(patient_id, [])
        return [
            {"id": gid, "name": self.patients[gid]["name"], "phone": self.patients[gid].get("phone", "")}
            for gid in guardian_ids
            if gid in self.patients
        ]

    def is_guardian_of(self, caller_id: str, patient_id: str) -> bool:
        """Check if caller_id is an authorised guardian of patient_id."""
        caller = self.patients.get(caller_id)
        if caller is None:
            return False
        return patient_id in caller.get("guardian_of", [])

    # ------------------------------------------------------------------
    # Mutation helpers (caller MUST hold self.lock)
    # ------------------------------------------------------------------
    def _next_appointment_id(self) -> str:
        return f"ap_{len(self.appointments) + 1:04d}"

    def _add_appointment(self, appt: dict) -> None:
        self.appointments.append(appt)
        self._appt_index[appt["id"]] = appt

    def get_appointment(self, appointment_id: str) -> dict | None:
        return self._appt_index.get(appointment_id)

    def compute_end_time(self, start: str) -> str:
        """Add slot_minutes to start time and return HH:MM."""
        t = datetime.strptime(start, "%H:%M")
        t += timedelta(minutes=self.slot_minutes)
        return t.strftime("%H:%M")
