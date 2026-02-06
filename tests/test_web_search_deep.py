
import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ankita')))

from tools import web_search

class TestWebSearch(unittest.TestCase):
    
    @patch("tools.web_search.requests.get")
    def test_duckduckgo_fallback_search(self, mock_get):
        # Configure mock for DuckDuckGo response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "AbstractText": "Python is a high-level programming language.",
            "Heading": "Python (programming language)",
            "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "RelatedTopics": [
                {
                    "Text": "Python Software Foundation",
                    "FirstURL": "https://python.org"
                }
            ]
        }
        mock_get.return_value = mock_response

        # Call search with no API keys (default behavior)
        with patch.dict(os.environ, {}, clear=True):
            result = web_search.run("python programming")
            
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["query"], "python programming")
        self.assertTrue(len(result["results"]) > 0)
        
        # Verify first result
        first = result["results"][0]
        self.assertEqual(first["source"], "DuckDuckGo")
        self.assertEqual(first["title"], "Python (programming language)")
        self.assertIn("Python is a high-level", first["snippet"])

    @patch("tools.web_search.requests.get")
    def test_wttr_weather(self, mock_get):
        # Configure mock for wttr.in response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "current_condition": [{
                "temp_C": "25",
                "FeelsLikeC": "28",
                "weatherDesc": [{"value": "Sunny"}]
            }]
        }
        mock_get.return_value = mock_response

        # Test weather trigger
        result = web_search.run("weather in London")
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["results"][0]["source"], "wttr.in")
        self.assertIn("25°C", result["results"][0]["snippet"])

    @patch("tools.web_search.requests.get")
    def test_crypto_price(self, mock_get):
        # Configure mock for CoinGecko response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "bitcoin": {"usd": 50000}
        }
        mock_get.return_value = mock_response

        # Test crypto trigger
        result = web_search.run("bitcoin price")
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["results"][0]["source"], "CoinGecko")
        self.assertIn("50000", result["results"][0]["snippet"])

    @patch("tools.web_search.requests.post")
    def test_tavily_search(self, mock_post):
        # Configure mock for Tavily response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Tavily Result",
                    "content": "This is a test result from Tavily.",
                    "url": "https://tavily.com"
                }
            ]
        }
        mock_post.return_value = mock_response

        # Test with Tavily API Key
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            result = web_search.run("test query")
            
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["results"][0]["source"], "Tavily")
        self.assertEqual(result["results"][0]["title"], "Tavily Result")

    @patch("tools.web_search.requests.get")
    def test_serpapi_search(self, mock_get):
        # Configure mock for SerpAPI response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "organic_results": [
                {
                    "title": "SerpAPI Result",
                    "snippet": "This is a test result from SerpAPI.",
                    "link": "https://serpapi.com"
                }
            ]
        }
        mock_get.return_value = mock_response

        # Test with SerpAPI Key and Provider set
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "serpapi", "SERPAPI_API_KEY": "test-key"}):
            result = web_search.run("test query")
            
        self.assertEqual(result["status"], "success")
        # Note: The code lowercases the search provider check, so 'serpapi' works
        self.assertEqual(result["results"][0]["source"], "SerpAPI")
        self.assertEqual(result["results"][0]["title"], "SerpAPI Result")

if __name__ == '__main__':
    unittest.main()
