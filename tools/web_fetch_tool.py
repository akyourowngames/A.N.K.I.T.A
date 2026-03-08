#!/usr/bin/env python3
"""
Web Fetch Tool - Deep content extraction for full page reads
Uses Firecrawl for clean content extraction (~1,300ms)
"""

import os
import requests
from typing import Optional


class WebFetchTool:
    """Web fetch tool for deep content extraction"""
    
    def __init__(self):
        self.firecrawl_api_key = os.getenv('FIRECRAWL_API_KEY')
    
    @staticmethod
    def get_schema():
        """Get tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": "fetch_webpage",
                "description": "Fetch and extract full content from a specific URL. Use this when you need to read an entire article or page, not just search results. Returns clean text without HTML.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to fetch and extract content from"
                        },
                        "extract_type": {
                            "type": "string",
                            "enum": ["full", "summary", "main_content"],
                            "description": "What to extract (full=entire page, summary=key points, main_content=article body only)"
                        }
                    },
                    "required": ["url"]
                }
            }
        }
    
    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute web fetch"""
        tool = WebFetchTool()
        
        url = arguments.get("url", "")
        extract_type = arguments.get("extract_type", "main_content")
        
        if not url:
            return "Error: No URL provided"
        
        # Try Firecrawl first (best for AI consumption)
        if tool.firecrawl_api_key:
            content = tool._fetch_firecrawl(url, extract_type)
            if content:
                return content
        
        # Fallback to simple requests
        return tool._fetch_simple(url)
    
    def _fetch_firecrawl(self, url: str, extract_type: str) -> Optional[str]:
        """Fetch using Firecrawl API (~1,300ms, clean extraction)"""
        try:
            response = requests.post(
                'https://api.firecrawl.dev/v0/scrape',
                headers={
                    'Authorization': f'Bearer {self.firecrawl_api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'url': url,
                    'formats': ['markdown'],
                    'onlyMainContent': extract_type == 'main_content'
                },
                timeout=10
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            
            if not data.get('success'):
                return None
            
            # Extract clean markdown content
            content = data.get('data', {}).get('markdown', '')
            
            if not content:
                return None
            
            # Format output
            title = data.get('data', {}).get('metadata', {}).get('title', 'Untitled')
            output = [
                f"# {title}",
                f"Source: {url}\n",
                content
            ]
            
            return '\n'.join(output)
        
        except Exception as e:
            print(f"  Firecrawl error: {e}")
            return None
    
    def _fetch_simple(self, url: str) -> str:
        """Simple fallback fetch (no API key needed)"""
        try:
            response = requests.get(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                timeout=10
            )
            
            if response.status_code != 200:
                return f"Error: Failed to fetch URL (status {response.status_code})"
            
            # Very basic HTML stripping (not ideal, but works without dependencies)
            import re
            text = response.text
            
            # Remove script and style tags
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', '', text)
            
            # Clean up whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text = text.strip()
            
            # Limit length
            if len(text) > 10000:
                text = text[:10000] + "\n\n[Content truncated...]"
            
            return f"Content from {url}:\n\n{text}"
        
        except Exception as e:
            return f"Error fetching URL: {str(e)}"
