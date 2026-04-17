"""BearAgent — fresh-session Claude API wrapper for thesis red-team critique.

Run once at thesis creation time. Never in the scheduled cron. No chat history,
no system prompt, single user message. Protects against sycophantic carryover.
"""

import re
from datetime import datetime, timezone
from typing import Optional

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


BEAR_PROMPT_TEMPLATE = """You are a skeptical short-seller reviewing the thesis below.

Rules:
1. Do NOT affirm any claim. Your job is disagreement.
2. List the 3 strongest reasons this thesis is wrong, ranked by probability, not severity.
3. For each reason, state what observable evidence in the next 30/90/180 days would confirm it.
4. Identify any factual claim that cannot be verified from public filings — flag it [UNVERIFIED].
5. End with: "Minimum price/event that would prove the thesis-holder wrong" — a single falsifiable line.

Do not hedge. Do not offer balance. Assume the author is overconfident and biased long.

THESIS: {thesis}
INVALIDATION AS STATED: {invalidation_as_text}
PRE-MORTEM BY AUTHOR: {pre_mortem}
"""


UNVERIFIED_RE = re.compile(r"\[UNVERIFIED\][^.\n]*[.\n]", re.IGNORECASE)
MINIMUM_LINE_RE = re.compile(r"^\s*Minimum[^\n]*", re.IGNORECASE | re.MULTILINE)


def parse_bear_response(text: str) -> dict:
    """Deterministic extractor. No LLM re-prompting."""
    if not text or not text.strip():
        return {"red_team_critique": "", "unverified_claims": [], "bear_floor": None}
    unverified = [m.group(0).strip() for m in UNVERIFIED_RE.finditer(text)]
    floor_match = MINIMUM_LINE_RE.search(text)
    floor = floor_match.group(0).strip() if floor_match else None
    return {
        "red_team_critique": text.strip(),
        "unverified_claims": unverified,
        "bear_floor": floor,
    }


class BearAgent:
    def __init__(self, api_key: str, model: str = "claude-opus-4-7"):
        if Anthropic is None:
            raise RuntimeError("anthropic package not installed")
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def critique(self, thesis: str, invalidation_as_text: str, pre_mortem: str) -> dict:
        prompt = BEAR_PROMPT_TEMPLATE.format(
            thesis=thesis,
            invalidation_as_text=invalidation_as_text,
            pre_mortem=pre_mortem,
        )
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in msg.content if hasattr(block, "text"))
            parsed = parse_bear_response(text)
            parsed["bear_agent_model"] = self.model
            parsed["bear_agent_run_at"] = datetime.now(timezone.utc).isoformat()
            parsed["error"] = None
            return parsed
        except Exception as e:
            return {
                "red_team_critique": "",
                "unverified_claims": [],
                "bear_floor": None,
                "bear_agent_model": self.model,
                "bear_agent_run_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
