---
name: web-research
description: Deep research on any topic using layered web tools. Use when asked to research, investigate, compare, or gather facts from the internet.
suggested-tools: web_search, web_fetch, scrape_low, scrape_mid, scrape_high
---
# Web Research

1. Start broad: `web_search` with 2-3 query angles. Fuse and de-dupe the results yourself — don't just read the first hit.
2. Go deep on the best sources with `web_fetch`. If extraction is thin or the page is a script shell, escalate: `scrape_low` → `scrape_mid` (blocked/JS pages) → `scrape_high` (multi-page crawl, bounded).
3. Cross-check important claims across at least two independent sources. One source is a rumor.
4. Report: what you found, where it came from (URLs), what disagrees, and your confidence level. Never present a single-source claim as fact.
5. Respect the SSRF guard — no loopback/private hosts. If a page won't yield, say so and move on instead of hammering it.
