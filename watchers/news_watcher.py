"""
NewsWatcher — Keyword News Monitor for A.N.K.I.T.A.

Continuously scans news for user-defined keywords.
Deduplicates articles across sessions using URL/title hashes.

Config (news_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 600,
        "keywords": ["AI India", "Helper ID", "artificial intelligence"]
    }
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine


class NewsWatcher(BaseWatcher):
    """Monitors news headlines for configured keywords. Deduplicates across sessions."""

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
        # Keep in-memory set for fast lookup (reconstructed from state on load)
        self._seen: Set[str] = set(self.state.get("seen_hashes", []))

        # Cap the hash set size to prevent unbounded growth
        self._max_seen = 5000

    def _check(self) -> Optional[str]:
        """Search news for each keyword and alert on new articles."""
        keywords: List[str] = self.config.get("keywords", [])
        if not keywords:
            return None

        new_alerts: List[str] = []

        for keyword in keywords:
            try:
                articles = self._fetch_news(keyword)
            except Exception as exc:
                print(f"[NewsWatcher] Fetch failed for '{keyword}': {exc}", flush=True)
                continue

            for article in articles:
                article_hash = self._hash_article(article)
                if article_hash in self._seen:
                    continue

                # New article!
                self._seen.add(article_hash)
                title = article.get("title", "").strip()
                source = article.get("source", "").strip()
                url = article.get("url", "").strip()

                if title:
                    alert_line = f"📰 [{keyword}] {title}"
                    if source:
                        alert_line += f"  — {source}"
                    if url:
                        alert_line += f"\n   🔗 {url}"
                    new_alerts.append(alert_line)

        # Persist updated seen set (trimmed to max size)
        if len(self._seen) > self._max_seen:
            # Keep most recent entries (convert to list, trim, convert back)
            seen_list = list(self._seen)
            self._seen = set(seen_list[-self._max_seen:])

        self.state["seen_hashes"] = list(self._seen)
        self._save_state()

        if new_alerts:
            count = len(new_alerts)
            header = f"🗞️ {count} new article{'s' if count > 1 else ''} found!\n"
            return header + "\n\n".join(new_alerts[:5])  # Cap at 5 per cycle

        return None

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
