# Web Search System Setup

ANKITA uses AI-native search APIs based on 2026 benchmarks for optimal agent performance.

## Quick Start

1. **Get API Keys (Free Tiers)**

   **Brave Search** (Recommended Primary)
   - Sign up: https://brave.com/search/api/
   - Free tier: 2,000 queries/month
   - Latency: 669ms avg (fastest in benchmark)
   - Agent Score: 14.89 (highest quality)

   **Tavily** (Recommended Fallback)
   - Sign up: https://tavily.com
   - Free tier: 1,000 credits/month
   - Latency: 998ms avg
   - Agent Score: 13.67

   **Firecrawl** (Optional - Deep Content)
   - Sign up: https://firecrawl.dev
   - For full page extraction when needed
   - Latency: ~1,300ms

2. **Add Keys to .env**

   ```bash
   # Brave Search (primary)
   BRAVE_API_KEY=your_brave_api_key_here

   # Tavily (fallback)
   TAVILY_API_KEY=your_tavily_api_key_here

   # Firecrawl (optional)
   FIRECRAWL_API_KEY=your_firecrawl_api_key_here
   ```

3. **Test the System**

   ```bash
   python test_web_search.py
   ```

## Architecture

### Three-Tier Approach

1. **Tier 1: Fast Facts** (Brave Search)
   - Use for: Quick lookups, current events, factual questions
   - Latency: ~669ms
   - Returns: Clean JSON with dense excerpts

2. **Tier 2: Deep Content** (Firecrawl)
   - Use for: Reading full articles, documentation
   - Latency: ~1,300ms
   - Returns: Clean markdown, no HTML

3. **Tier 3: Fallback** (Tavily)
   - Use when: Brave unavailable or rate limited
   - Latency: ~998ms
   - Returns: AI-optimized results

### Intelligent Caching

- **Cache hit**: <5ms (instant)
- **Cache TTL by type**:
  - News: 5 minutes
  - General: 1 hour
  - Reference: 24 hours

### Source Quality Filtering

**Blocked domains** (low quality):
- reddit.com, quora.com, pinterest.com
- Social media (facebook, twitter, instagram)

**Preferred domains** (high quality):
- wikipedia.org, github.com, stackoverflow.com
- Official documentation sites

## Usage

### In Code

```python
from tools.web_search_tool import WebSearchTool

# Basic search
result = WebSearchTool.execute({
    "query": "Python async programming",
    "search_type": "general",
    "max_results": 5
})

# News search (shorter cache)
result = WebSearchTool.execute({
    "query": "latest AI developments",
    "search_type": "news",
    "max_results": 3
})
```

### In Chat

Just ask naturally - skills auto-trigger:

```
You: search for Python async best practices
Agent: [Activates web-search skill, uses search_web tool]

You: read that first article
Agent: [Activates web-fetch skill, uses fetch_webpage tool]
```

## Performance

### Latency Budget

| Operation | Target | Actual (Benchmark) |
|-----------|--------|-------------------|
| Cache hit | <5ms | ~2ms |
| Brave search | <700ms | 669ms |
| Tavily search | <1000ms | 998ms |
| Firecrawl fetch | <1500ms | ~1,300ms |
| 3 parallel searches | <800ms | ~700ms |

### Why This Matters

Traditional search APIs (SerpAPI, Google Custom Search) return raw HTML and URLs, forcing agents to:
1. Parse HTML (slow)
2. Make multiple sequential searches (compounds latency)
3. Filter irrelevant results (wastes tokens)

AI-native APIs return clean, structured data ready for agent consumption:
- No HTML parsing needed
- Dense excerpts (token-efficient)
- Pre-filtered for relevance
- Optimized for LLM context windows

## Benchmark Results (2026)

Based on comprehensive testing across 8 providers:

| Provider | Agent Score | Latency | Notes |
|----------|-------------|---------|-------|
| Brave Search | 14.89 | 669ms | ✓ Best overall |
| Firecrawl | 14.5 | 1,300ms | ✓ Best for content |
| Exa | 14.3 | 850ms | Good for semantic |
| Parallel Search | 14.2 | 720ms | Good alternative |
| Tavily | 13.67 | 998ms | ✓ Best free tier |
| You.com | 13.1 | 1,200ms | Decent |
| Perplexity | 12.9 | 11,000ms | ✗ Too slow |
| SerpAPI | 12.28 | 1,500ms | ✗ High irrelevance |

## Troubleshooting

**No results returned**
- Check API keys are set in .env
- Verify API key is valid (test at provider website)
- Check rate limits (free tiers have monthly caps)

**Slow searches**
- First search is always slower (cache miss)
- Subsequent identical searches are <5ms (cached)
- Check internet connection

**"Error: No search API keys configured"**
- Set at least one: BRAVE_API_KEY or TAVILY_API_KEY
- Restart chatbot after adding keys

## Cost Optimization

1. **Use caching** - Identical queries are free after first hit
2. **Choose right search type** - Reference content caches 24hr
3. **Limit max_results** - Default 5 is usually enough
4. **Use fetch_webpage sparingly** - Only when search snippets insufficient
5. **Parallel searches** - Multiple searches in one turn = same latency as one

## Advanced: Parallel Searches

For complex queries needing multiple perspectives:

```python
# Instead of sequential (slow):
result1 = search("Python async")
result2 = search("Python threading")
# Total: ~1,400ms

# Use parallel (fast):
import concurrent.futures
with concurrent.futures.ThreadPoolExecutor() as executor:
    future1 = executor.submit(search, "Python async")
    future2 = executor.submit(search, "Python threading")
    result1 = future1.result()
    result2 = future2.result()
# Total: ~700ms (both run simultaneously)
```

Skills automatically handle this when needed.
