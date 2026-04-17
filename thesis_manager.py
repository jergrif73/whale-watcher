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

    def update_critique(self, thesis_id: str, critique: dict) -> None:
        """Persist bear-agent output onto an existing thesis."""
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                t["red_team_critique"] = critique.get("red_team_critique", "")
                t["unverified_claims"] = critique.get("unverified_claims", [])
                t["bear_agent_model"] = critique.get("bear_agent_model", "")
                t["bear_agent_run_at"] = critique.get("bear_agent_run_at", "")
                if critique.get("bear_floor"):
                    t["invalidation_criteria"].append({
                        "type": "bear_floor",
                        "condition": critique["bear_floor"],
                        "auto": False,
                    })
                self._save()
                return
        raise KeyError(thesis_id)

    def append_override_event(self, thesis_id: str, signal: str, price: float, date: str) -> None:
        for t in self._data["theses"]:
            if t["id"] == thesis_id:
                t["override_events"].append({"date": date, "signal": signal, "price": price})
                self._save()
                return

    # -- Email rendering --

    def render_email_section(self, current_prices: dict) -> str:
        """Return an HTML fragment (wrapped in <tr><td>...) for the
        'Active Theses' email section. Empty string when no active theses.
        """
        actives = [t for t in self._data["theses"] if t["status"] == "active"]
        if not actives:
            return ""
        rows = []
        for t in actives:
            sym = t["ticker"]
            price = current_prices.get(sym)
            price_txt = f"${price:.2f}" if price else "?"
            conds_html = ""
            for crit in t["invalidation_criteria"]:
                icon = "●" if crit["auto"] else "⚠"
                manual_tag = (' <span style="color:#d29922">(manual check)</span>'
                              if not crit["auto"] else "")
                conds_html += (
                    f'<li style="color:#8b949e;font-size:12px;">{icon} '
                    f'{crit["condition"]}{manual_tag}</li>'
                )
            critique_html = ""
            if t.get("red_team_critique"):
                critique_html = (
                    '<details style="margin-top:8px;color:#8b949e;font-size:12px;">'
                    '<summary style="cursor:pointer;color:#58a6ff;">▼ Bear critique (fresh-session)</summary>'
                    '<div style="padding:8px;background:#0d1117;border-left:2px solid #f85149;">'
                    f'{t["red_team_critique"]}</div></details>'
                )
            rows.append(
                '<tr><td style="padding:12px;border-bottom:1px solid #30363d;">'
                f'<div><strong style="color:#58a6ff;">{sym}</strong> '
                f'— entered {t["created"]} · conviction {t["conviction"]}/10 '
                f'· Current: {price_txt}</div>'
                '<div style="margin-top:6px;padding:8px;background:#161b22;'
                'border-left:2px solid #58a6ff;color:#e6edf3;font-size:13px;">'
                f'{t["thesis"]}</div>'
                f'<ul style="margin:6px 0 0 0;padding-left:20px;">{conds_html}</ul>'
                f'{critique_html}'
                '</td></tr>'
            )
        return (
            '<tr><td style="padding-top:30px;">'
            '<h3 style="margin:0 0 15px 0;color:#e6edf3;'
            'border-bottom:1px solid #30363d;padding-bottom:5px;">'
            '🧠 Active Theses</h3>'
            '<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;">{"".join(rows)}</table>'
            '</td></tr>'
        )
