"""Thesis persistence, status lifecycle, and email-section rendering.

Storage: docs/data/theses.json (git-versioned). Atomic writes via
rename. Malformed JSON is backed up and treated as empty.
"""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from invalidation_evaluator import InvalidationEvaluator


VALID_TRANSITIONS = {
    "active":      {"invalidated", "vindicated", "expired", "orphaned"},
    "orphaned":    {"invalidated", "vindicated"},
    "invalidated": set(),   # terminal
    "vindicated":  set(),   # terminal
    "expired":     set(),   # terminal
}


class InvalidStatusTransition(Exception):
    pass


class ThesisManager:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.evaluator = InvalidationEvaluator()
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"theses": [], "version": 1}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.path.with_name(f"{self.path.name}.corrupt-{ts}")
            shutil.copy2(self.path, backup)
            return {"theses": [], "version": 1}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- API --

    def list_all(self) -> List[dict]:
        return list(self._data["theses"])

    def get_active(self, ticker: str) -> Optional[dict]:
        for t in self._data["theses"]:
            if t["ticker"].upper() == ticker.upper() and t["status"] == "active":
                return t
        return None

    def add(self, ticker: str, thesis: str, invalidation: List[str],
            conviction: int, pre_mortem: str, created: str,
            author: str = "jeremiah") -> dict:
        tid = f"{ticker.lower()}-{created}"
        conditions = []
        for raw in invalidation:
            c = self.evaluator.parse(raw)
            conditions.append({
                "type": c.type, "condition": c.raw, "auto": c.auto,
            })
        created_dt = datetime.strptime(created, "%Y-%m-%d")
        review_dt = created_dt + timedelta(days=180)
        review_iso = review_dt.strftime("%Y-%m-%d")
        thesis_obj = {
            "id": tid,
            "ticker": ticker.upper(),
            "created": created,
            "author": author,
            "thesis": thesis,
            "enter_tag": "",
            "conviction": conviction,
            "pre_mortem": pre_mortem,
            "invalidation_criteria": conditions,
            "red_team_critique": "",
            "unverified_claims": [],
            "bear_agent_model": "",
            "bear_agent_run_at": "",
            "status": "active",
            "review_date": review_iso,
            "review_checkpoints": {
                "30d":  {"due": (created_dt + timedelta(days=30)).strftime("%Y-%m-%d"),  "completed": False, "verdict": None},
                "90d":  {"due": (created_dt + timedelta(days=90)).strftime("%Y-%m-%d"),  "completed": False, "verdict": None},
                "180d": {"due": review_iso, "completed": False, "verdict": None},
            },
            "override_events": [],
            "outcome": None,
        }
        self._data["theses"].append(thesis_obj)
        self._save()
        return thesis_obj

    def set_status(self, thesis_id: str, new_status: str) -> None:
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                current = t["status"]
                if new_status not in VALID_TRANSITIONS.get(current, set()):
                    raise InvalidStatusTransition(
                        f"{current} -> {new_status} not allowed"
                    )
                t["status"] = new_status
                self._save()
                return
        raise KeyError(thesis_id)

    def append_override_event(self, thesis_id: str, signal: str, price: float, date: str) -> None:
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                t["override_events"].append({"date": date, "signal": signal, "price": price})
                self._save()
                return
