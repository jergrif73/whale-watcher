import unittest
from unittest.mock import MagicMock, patch

from bear_agent import BearAgent, parse_bear_response


SAMPLE_RESPONSE = """
1. COIN revenue is 95% transaction volume — if BTC consolidates sideways rather than bottoming, volumes compress and margins follow. Observable in 30/90/180d: quarterly trading volume declines, EPS miss vs consensus. [UNVERIFIED] Specific revenue breakdown figures.
2. Regulatory risk from SEC — pending enforcement actions could impair the core business. Observable: new SEC filings, 8-K disclosures.
3. Competitive pressure from Robinhood Crypto, Binance US — observable in market share data.

Minimum price/event that would prove the thesis-holder wrong: COIN trades below $140 for 5 consecutive sessions OR quarterly trading volume drops 30% YoY.
"""


class TestParseBearResponse(unittest.TestCase):
    def test_extracts_full_critique(self):
        parsed = parse_bear_response(SAMPLE_RESPONSE)
        self.assertIn("COIN revenue", parsed["red_team_critique"])

    def test_extracts_unverified_claims(self):
        parsed = parse_bear_response(SAMPLE_RESPONSE)
        self.assertEqual(len(parsed["unverified_claims"]), 1)
        self.assertIn("Specific revenue breakdown", parsed["unverified_claims"][0])

    def test_extracts_bear_floor(self):
        parsed = parse_bear_response(SAMPLE_RESPONSE)
        self.assertIn("$140", parsed["bear_floor"])

    def test_extracts_bear_floor_from_markdown_heading(self):
        markdown_response = """
Some critique content.

## Minimum price/event that would prove the thesis-holder wrong
**COIN closes below $140 on weekly basis AND Q4 transaction revenue prints down >20% YoY — either condition alone falsifies the linkage.**
"""
        parsed = parse_bear_response(markdown_response)
        self.assertIsNotNone(parsed["bear_floor"])
        self.assertIn("Minimum", parsed["bear_floor"])
        self.assertIn("$140", parsed["bear_floor"])
        self.assertNotIn("**", parsed["bear_floor"])
        self.assertNotIn("##", parsed["bear_floor"])

    def test_empty_response_returns_defaults(self):
        parsed = parse_bear_response("")
        self.assertEqual(parsed["red_team_critique"], "")
        self.assertEqual(parsed["unverified_claims"], [])
        self.assertIsNone(parsed["bear_floor"])


class TestBearAgent(unittest.TestCase):
    @patch("bear_agent.Anthropic")
    def test_critique_calls_api_with_fresh_session(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=SAMPLE_RESPONSE)]
        )

        agent = BearAgent(api_key="test-key")
        result = agent.critique(
            thesis="BTC halving bottom",
            invalidation_as_text="close < 140 for 5 sessions",
            pre_mortem="If BTC doesn't bottom by Q3",
        )
        mock_client.messages.create.assert_called_once()
        kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(len(kwargs["messages"]), 1)
        self.assertEqual(kwargs["messages"][0]["role"], "user")
        self.assertNotIn("system", kwargs)
        self.assertEqual(kwargs["model"], "claude-opus-4-7")
        self.assertIn("COIN revenue", result["red_team_critique"])

    @patch("bear_agent.Anthropic")
    def test_critique_handles_api_error_gracefully(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("rate limit")

        agent = BearAgent(api_key="test-key")
        result = agent.critique(
            thesis="x", invalidation_as_text="y", pre_mortem="z",
        )
        self.assertEqual(result["red_team_critique"], "")
        self.assertEqual(result["error"], "rate limit")


if __name__ == "__main__":
    unittest.main()
