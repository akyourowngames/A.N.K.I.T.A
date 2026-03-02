"""
NewsWatcher — Keyword News Monitor for A.N.K.I.T.A.

Continuously scans news for user-defined keywords.
Supports boolean keyword logic, priority levels, and sentiment tagging.
Deduplicates articles across sessions using URL/title hashes.

Config (news_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 600,
        "keywords": ["AI India", "artificial intelligence AND India NOT spam"],
        "keyword_priorities": {
            "AI India": "URGENT",
            "artificial intelligence": "FYI"
        }
    }

Keyword syntax (boolean logic):
    "AI AND India"          — both terms must appear
    "OpenAI OR Anthropic"  — either term must appear
    "AI NOT clickbait"     — first term yes, second term no
    "AI AND (India OR US)" — grouping via parentheses (simplified)
    "AI India"             — treated as phrase match (default)
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine

# Priority levels (higher = more urgent)
_PRIORITY_ORDER = {"URGENT": 3, "IMPORTANT": 2, "FYI": 1, "": 0}

# Simple positive/negative word lists for sentiment tagging
_POSITIVE_WORDS = {
    "breakthrough", "growth", "success", "launch", "gains", "record",
    "profit", "innovation", "approved", "wins", "awarded", "surge",
}
_NEGATIVE_WORDS = {
    "crash", "ban", "hack", "breach", "fine", "lawsuit", "fail",
    "outage", "drop", "loss", "fraud", "scam", "exploit", "attack",
    "recall", "shutdown", "crisis", "warning", "risk", "decline",
}


class NewsWatcher(BaseWatcher):
    """
    Monitors news headlines for configured keywords.
    Supports boolean AND/OR/NOT logic, priority tiers, and sentiment tagging.
    Deduplicates across sessions.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="NewsWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 600))

        # Persist seen article hashes to avoid duplicate alerts across restarts
        self.state.setdefault("seen_hashes", [])
        self._seen: Set[str] = set(self.state.get("seen_hashes", []))
        self._max_seen = 5000

    def _check(self) -> Optional[str]:
        """Search news for each keyword and alert on new articles."""
        keywords: List[str] = self.config.get("keywords", [])
        priorities: Dict[str, str] = self.config.get("keyword_priorities", {})
        if not keywords:
            return None

        # Collect (priority_level, alert_text) tuples
        new_alerts: List[Tuple[int, str]] = []

        for keyword in keywords:
            # Derive the search query (strip boolean operators for the API call)
            search_query = self._keyword_to_search_query(keyword)
            priority_label = priorities.get(keyword, "").upper()
            priority_level = _PRIORITY_ORDER.get(priority_label, 0)

            try:
                articles = self._fetch_news(search_query)
            except Exception as exc:
                print(f"[NewsWatcher] Fetch failed for '{keyword}': {exc}", flush=True)
                continue

            for article in articles:
                article_hash = self._hash_article(article)
                if article_hash in self._seen:
                    continue

                title = article.get("title", "").strip()
                source = article.get("source", "").strip()
                url = article.get("url", "").strip()

                if not title:
                    continue

                # Apply boolean filter on article text
                combined_text = (title + " " + article.get("snippet", "")).lower()
                if not self._matches_boolean(keyword, combined_text):
                    continue

                self._seen.add(article_hash)

                # Sentiment tag
                sentiment = self._detect_sentiment(title)
                sentiment_emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(sentiment, "⚪")

                # Priority tag
                priority_tag = f"[{priority_label}] " if priority_label else ""

                alert_line = f"📰 {sentiment_emoji} {priority_tag}[{keyword}] {title}"
                if source:
                    alert_line += f"  — {source}"
                if url:
                    alert_line += f"\n   🔗 {url}"

                new_alerts.append((priority_level, alert_line))

        # Sort by priority (URGENT first)
        new_alerts.sort(key=lambda x: x[0], reverse=True)

        # Trim seen set
        if len(self._seen) > self._max_seen:
            seen_list = list(self._seen)
            self._seen = set(seen_list[-self._max_seen:])

        self.state["seen_hashes"] = list(self._seen)
        self._save_state()

        if new_alerts:
            count = len(new_alerts)
            # Prepend URGENT count if any
            urgent_count = sum(1 for p, _ in new_alerts if p >= _PRIORITY_ORDER["URGENT"])
            header = f"🗞️ {count} new article{'s' if count > 1 else ''} found!"
            if urgent_count:
                header += f"  🚨 {urgent_count} URGENT!"
            return header + "\n\n" + "\n\n".join(a for _, a in new_alerts[:5])

        return None

    # ------------------------------------------------------------------
    # Boolean keyword matching
    # ------------------------------------------------------------------

    def _keyword_to_search_query(self, keyword: str) -> str:
        """
        Strip boolean operators to produce a clean search API query.
        'AI AND India NOT clickbait' → 'AI India'
        """
        clean = re.sub(r'\b(AND|OR|NOT)\b', ' ', keyword, flags=re.IGNORECASE)
        clean = re.sub(r'[()]', ' ', clean)
        return ' '.join(clean.split())

    def _matches_boolean(self, keyword: str, text: str) -> bool:
        """
        Evaluate simple boolean keyword expression against article text.

        Supports:
          - 'term'                 → phrase must appear
          - 'A AND B'              → both A and B must appear
          - 'A OR B'               → A or B must appear
          - 'A NOT B'              → A must appear, B must not
          - Combinations (left-to-right, no precedence grouping)

        Falls back to simple substring match if no operators detected.
        """
        kw = keyword.strip()
        # Simple phrase (no boolean operators) → substring match
        if not re.search(r'\b(AND|OR|NOT)\b', kw, re.IGNORECASE):
            return kw.lower() in text

        # Tokenize into terms and operators
        tokens = re.split(r'\s+(AND|OR|NOT)\s+', kw, flags=re.IGNORECASE)
        if len(tokens) == 1:
            return tokens[0].lower() in text

        # Start with first term
        result = tokens[0].strip().lower() in text
        i = 1
        while i < len(tokens) - 1:
            op = tokens[i].upper()
            term = tokens[i + 1].strip().lower()
            term_present = term in text
            if op == "AND":
                result = result and term_present
            elif op == "OR":
                result = result or term_present
            elif op == "NOT":
                result = result and not term_present
            i += 2

        return result

    # ------------------------------------------------------------------
    # Sentiment detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_sentiment(title: str) -> str:
        """
        Simple keyword-based sentiment detection on article title.
        Returns 'positive', 'negative', or 'neutral'.
        """
        words = set(re.findall(r'\w+', title.lower()))
        pos_hits = words & _POSITIVE_WORDS
        neg_hits = words & _NEGATIVE_WORDS
        if neg_hits and not pos_hits:
            return "negative"
        if pos_hits and not neg_hits:
            return "positive"
        return "neutral"

    def _fetch_news(self, keyword: str) -> List[Dict[str, Any]]:
        """
        Fetch news articles for a keyword.
        Tries the built-in search_news tool first, then falls back to RSS/HTTP.

        Returns list of dicts with: title, source, url, published_at
        """
        # Try the built-in search_news tool
        try:
            from tools.realtime_search import search_news  # type: ignore
            result = search_news(keyword, max_results=10)
            if isinstance(result, list) and result:
                return [
                    {
                        "title": r.get("title", ""),
                        "source": r.get("source", ""),
                        "url": r.get("url", r.get("link", "")),
                        "published_at": r.get("published_at", ""),
                    }
                    for r in result
                ]
            # Some implementations return a dict with 'results' key
            if isinstance(result, dict) and "results" in result:
                items = result["results"]
                return [
                    {
                        "title": r.get("title", ""),
                        "source": r.get("source", ""),
                        "url": r.get("url", r.get("link", "")),
                        "published_at": r.get("published_at", ""),
                    }
                    for r in items
                ]
        except Exception as exc:
            print(f"[NewsWatcher] search_news tool failed: {exc}", flush=True)

        # Fallback: Google News RSS
        try:
            import urllib.request
            import xml.etree.ElementTree as ET
            import urllib.parse

            encoded = urllib.parse.quote(keyword)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
            req = urllib.request.Request(url, headers={"User-Agent": "ANKITA/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            articles = []
            for item in root.findall(".//item")[:15]:
                title_el = item.find("title")
                link_el = item.find("link")
                source_el = item.find("source")
                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                source = source_el.text.strip() if source_el is not None and source_el.text else ""
                if title:
                    articles.append({"title": title, "url": link, "source": source, "published_at": ""})
            return articles
        except Exception as exc:
            print(f"[NewsWatcher] RSS fallback failed for '{keyword}': {exc}", flush=True)

        return []

    @staticmethod
    def _hash_article(article: Dict[str, Any]) -> str:
        """Create a stable hash for deduplication — uses URL if available, else title."""
        url = article.get("url", "").strip()
        title = article.get("title", "").strip().lower()
        key = url if url else title
        return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]
