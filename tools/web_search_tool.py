#!/usr/bin/env python3
"""
Web Search Tool - AI-native search with caching and parallel support
Uses Brave Search API (669ms latency, Agent Score 14.89)
"""

import os
import json
import time
import hashlib
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


class SearchCache:
    """Simple file-based cache for search results"""
    
    def __init__(self, cache_dir: str = ".cache/search"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_key(self, query: str, search_type: str = "general") -> str:
        """Generate cache key from query"""
        content = f"{query}:{search_type}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, query: str, search_type: str = "general", max_age_minutes: int = 60) -> Optional[Dict]:
        """Get cached result if fresh enough"""
        cache_key = self._get_cache_key(query, search_type)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            
            # Check age
            cached_time = datetime.fromisoformat(cached['timestamp'])
            age = datetime.now() - cached_time
            
            if age < timedelta(minutes=max_age_minutes):
                return cached['data']
            
            # Expired, delete
            cache_file.unlink()
            return None
        
        except Exception:
            return None
    
    def set(self, query: str, data: Dict, search_type: str = "general"):
        """Cache search result"""
        cache_key = self._get_cache_key(query, search_type)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'query': query,
                    'data': data
                }, f)
        except Exception:
            pass


class WebSearchTool:
    """Web search tool using Brave Search API"""
    
    # Source quality filtering
    BLOCKED_DOMAINS = [
        'reddit.com', 'quora.com', 'pinterest.com',
        'facebook.com', 'twitter.com', 'instagram.com'
    ]
    
    PREFERRED_DOMAINS = [
        'wikipedia.org', 'github.com', 'stackoverflow.com',
        'docs.python.org', 'developer.mozilla.org'
    ]
    
    def __init__(self):
        self.cache = SearchCache()
        self.bing_api_key = os.getenv('BING_API_KEY')
        self.tavily_api_key = os.getenv('TAVILY_API_KEY')
        self.exa_api_key = os.getenv('EXA_API_KEY')
    
    @staticmethod
    def get_schema():
        """Get tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the web for current information using AI-optimized search (Bing Search API). For semantic/conceptual queries, automatically uses Exa. Returns clean, structured results ready for agent consumption.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["general", "news", "reference", "semantic"],
                            "description": "Type of search (general=keyword, semantic=conceptual, news=5min cache, reference=24hr cache)"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    
    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute web search"""
        tool = WebSearchTool()
        
        query = arguments.get("query", "")
        search_type = arguments.get("search_type", "general")
        max_results = arguments.get("max_results", 5)
        
        if not query:
            return "Error: No search query provided"
        
        # Determine cache TTL based on search type
        cache_ttl = {
            "news": 5,      # 5 minutes for news
            "general": 60,  # 1 hour for general
            "reference": 1440,  # 24 hours for reference
            "semantic": 60  # 1 hour for semantic
        }.get(search_type, 60)
        
        # Check cache first (under 5ms)
        cached = tool.cache.get(query, search_type, cache_ttl)
        if cached:
            return tool._format_results(cached, from_cache=True)
        
        # For semantic queries, try Exa first (850ms avg, best for conceptual)
        if search_type == "semantic" and tool.exa_api_key:
            results = tool._search_exa(query, max_results)
            if results:
                tool.cache.set(query, results, search_type)
                return tool._format_results(results, from_cache=False)
        
        # Try Bing Search for keyword queries
        if tool.bing_api_key:
            results = tool._search_bing(query, max_results)
            if results:
                tool.cache.set(query, results, search_type)
                return tool._format_results(results, from_cache=False)
        
        # Fallback to Tavily
        if tool.tavily_api_key:
            results = tool._search_tavily(query, max_results)
            if results:
                tool.cache.set(query, results, search_type)
                return tool._format_results(results, from_cache=False)
        
        # Last resort: Exa if available
        if tool.exa_api_key:
            results = tool._search_exa(query, max_results)
            if results:
                tool.cache.set(query, results, search_type)
                return tool._format_results(results, from_cache=False)
        
        return "Error: No search API keys configured. Set BING_API_KEY, EXA_API_KEY, or TAVILY_API_KEY in .env"
    
    def _search_bing(self, query: str, max_results: int = 5) -> Optional[List[Dict]]:
        """Search using Bing Search API"""
        try:
            start_time = time.time()
            
            response = requests.get(
                'https://api.bing.microsoft.com/v7.0/search',
                headers={
                    'Ocp-Apim-Subscription-Key': self.bing_api_key
                },
                params={
                    'q': query,
                    'count': max_results,
                    'textDecorations': False,
                    'textFormat': 'Raw'
                },
                timeout=5
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            results = []
            
            # Extract web results
            for item in data.get('webPages', {}).get('value', [])[:max_results]:
                url = item.get('url', '')
                
                # Apply source quality filtering
                if any(blocked in url for blocked in self.BLOCKED_DOMAINS):
                    continue
                
                # Extract clean content
                title = item.get('name', '')
                description = item.get('snippet', '')
                
                # Combine title and description for dense excerpt
                content = f"{title}\n{description}"
                
                results.append({
                    'title': title,
                    'url': url,
                    'content': content,
                    'published': item.get('dateLastCrawled', 'Unknown'),
                    'is_preferred': any(pref in url for pref in self.PREFERRED_DOMAINS)
                })
            
            # Sort: preferred sources first, maintain original order for rest
            results.sort(key=lambda x: not x['is_preferred'])
            
            latency = (time.time() - start_time) * 1000
            print(f"  Bing Search: {latency:.0f}ms")
            
            return results
        
        except Exception as e:
            print(f"  Bing Search error: {e}")
            return None
    
    def _search_tavily(self, query: str, max_results: int = 5) -> Optional[List[Dict]]:
        """Search using Tavily API (998ms avg latency, fallback)"""
        try:
            start_time = time.time()
            
            response = requests.post(
                'https://api.tavily.com/search',
                headers={'Content-Type': 'application/json'},
                json={
                    'api_key': self.tavily_api_key,
                    'query': query,
                    'max_results': max_results,
                    'include_answer': False,
                    'include_raw_content': False
                },
                timeout=5
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            results = []
            
            for item in data.get('results', [])[:max_results]:
                url = item.get('url', '')
                
                # Apply source quality filtering
                if any(blocked in url for blocked in self.BLOCKED_DOMAINS):
                    continue
                
                results.append({
                    'title': item.get('title', ''),
                    'url': url,
                    'content': item.get('content', ''),
                    'published': 'Unknown',
                    'is_preferred': any(pref in url for pref in self.PREFERRED_DOMAINS)
                })
            
            # Sort: preferred sources first, maintain original order for rest
            results.sort(key=lambda x: not x['is_preferred'])
            
            latency = (time.time() - start_time) * 1000
            print(f"  Tavily Search: {latency:.0f}ms")
            
            return results
        
        except Exception as e:
            print(f"  Tavily Search error: {e}")
            return None
    
    def _search_exa(self, query: str, max_results: int = 5) -> Optional[List[Dict]]:
        """Search using Exa API (850ms avg latency, best for semantic/conceptual queries)"""
        try:
            start_time = time.time()
            
            response = requests.post(
                'https://api.exa.ai/search',
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': self.exa_api_key
                },
                json={
                    'query': query,
                    'num_results': max_results,
                    'use_autoprompt': True,
                    'type': 'neural',
                    'contents': {
                        'text': {
                            'max_characters': 500
                        }
                    }
                },
                timeout=5
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            results = []
            
            for item in data.get('results', [])[:max_results]:
                url = item.get('url', '')
                
                # Apply source quality filtering
                if any(blocked in url for blocked in self.BLOCKED_DOMAINS):
                    continue
                
                # Extract text content
                text_content = item.get('text', '')
                if not text_content:
                    text_content = item.get('snippet', '')
                
                results.append({
                    'title': item.get('title', ''),
                    'url': url,
                    'content': text_content,
                    'published': item.get('published_date', 'Unknown'),
                    'is_preferred': any(pref in url for pref in self.PREFERRED_DOMAINS)
                })
            
            # Sort: preferred sources first, maintain original order for rest
            results.sort(key=lambda x: not x['is_preferred'])
            
            latency = (time.time() - start_time) * 1000
            print(f"  Exa Search: {latency:.0f}ms")
            
            return results
        
        except Exception as e:
            print(f"  Exa Search error: {e}")
            return None
    
    def _format_results(self, results: List[Dict], from_cache: bool = False) -> str:
        """Format search results for agent consumption"""
        if not results:
            return "No results found"
        
        cache_indicator = " [cached]" if from_cache else ""
        output = [f"Search Results{cache_indicator}:\n"]
        
        for i, result in enumerate(results, 1):
            preferred = " ⭐" if result.get('is_preferred') else ""
            output.append(f"{i}. {result['title']}{preferred}")
            output.append(f"   URL: {result['url']}")
            output.append(f"   {result['content'][:200]}...")
            if result.get('published') != 'Unknown':
                output.append(f"   Published: {result['published']}")
            output.append("")
        
        return '\n'.join(output)
