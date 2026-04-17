import unittest
from unittest.mock import patch, MagicMock
from whale_watcher_agent import MarketAgent, TechnicalAnalyzer
import json
from datetime import datetime, timedelta

class TestMarketAgent(unittest.TestCase):
    
    def setUp(self):
        # Create the agent
        self.agent = MarketAgent()
        
    def generate_fake_stock_data(self, trend="UP", volatility="HIGH"):
        """Generates 100 days of fake stock data to test logic"""
        data = {"Time Series (Daily)": {}}
        base_price = 100.0
        
        # Generate 100 days of history
        for i in range(100):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            
            # Create a fake trend
            if trend == "UP":
                price = base_price - (i * 0.5) # Price was lower in the past
            else:
                price = base_price + (i * 0.5) # Price was higher in the past
                
            # Create volume (High volume for today to trigger alert)
            if i == 0 and volatility == "HIGH":
                volume = 10000000 # Huge volume today
            else:
                volume = 1000000  # Normal volume
                
            data["Time Series (Daily)"][date] = {
                "4. close": str(price),
                "5. volume": str(volume)
            }
        return data

    @patch('whale_watcher_agent.requests.get')
    @patch.dict('os.environ', {'ALPHA_VANTAGE_KEY': 'TEST_KEY', 'SENDER_EMAIL': 'test@test.com'})
    def test_logic_without_api(self, mock_get):
        print("\n--- 🧪 STARTING SANDBOX TEST ---")
        
        # 1. Setup Mock Data (The "Fake" Market)
        # We simulate NVDA having a huge rally, and MSTR crashing
        fake_nvda = self.generate_fake_stock_data(trend="UP", volatility="HIGH")
        fake_mstr = self.generate_fake_stock_data(trend="DOWN", volatility="HIGH")
        
        fake_crypto = {
            "bitcoin": {"usd": 90000, "usd_24h_change": -5.0},
            "solana": {"usd": 150, "usd_24h_change": 12.0} # Moonshot!
        }

        # 2. Tell the mock how to respond
        def side_effect(url):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            
            if "NVDA" in url:
                mock_resp.json.return_value = fake_nvda
            elif "MSTR" in url:
                mock_resp.json.return_value = fake_mstr
            elif "coingecko" in url:
                # Extract coin id from url for simple mock logic
                if "bitcoin" in url: mock_resp.json.return_value = {"bitcoin": fake_crypto["bitcoin"]}
                elif "solana" in url: mock_resp.json.return_value = {"solana": fake_crypto["solana"]}
                else: mock_resp.json.return_value = {}
            else:
                # Default empty for others to speed up test
                mock_resp.json.return_value = {}
            return mock_resp

        mock_get.side_effect = side_effect

        # 3. Run the Agent Logic
        print("🤖 Agent is 'scanning' fake markets...")
        
        # We limit the watchlist for the test to just 2 stocks to keep output clean
        # We temporarily overwrite the agent's list (This is allowed in Python)
        import whale_watcher_agent
        whale_watcher_agent.STOCKS_TO_WATCH = ['NVDA', 'MSTR']
        whale_watcher_agent.CRYPTO_IDS = ['bitcoin', 'solana']
        
        # Remove the sleep timer so the test is instant
        whale_watcher_agent.time.sleep = lambda x: None 

        report = self.agent.generate_report()
        
        # 4. Print the Result
        print("\n📄 GENERATED REPORT PREVIEW:")
        print("-" * 40)
        print(report)
        print("-" * 40)
        
        # 5. Verify Logic
        self.assertIn("NVDA", report)
        self.assertIn("MSTR", report)
        print("\n✅ TEST PASSED: Logic is sound. No API keys were used.")

    def test_sparkline_png_is_valid(self):
        """_build_sparkline_png must return a data URI whose base64 payload starts with the PNG magic bytes."""
        prices = [100.0 + i * 0.5 for i in range(63)]  # ~3 months of daily prices
        data_uri = TechnicalAnalyzer._build_sparkline_png(prices)
        self.assertTrue(data_uri.startswith("data:image/png;base64,"),
                        "data URI must have PNG MIME prefix")
        b64_payload = data_uri.split(",", 1)[1]
        # PNG magic bytes base64-encode to "iVBORw0KGgo" at the start of the stream
        self.assertTrue(b64_payload.startswith("iVBORw0KGgo"),
                        f"PNG magic bytes not found; got prefix: {b64_payload[:20]!r}")
        print("\n✅ TEST PASSED: sparkline PNG magic bytes confirmed.")

if __name__ == '__main__':
    unittest.main()
