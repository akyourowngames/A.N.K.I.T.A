# 🚀 ANKITA Quick Reference — New Capabilities

## LLM-Powered Classification

### What Changed
- ❌ Old: Brittle keyword matching (270 lines)
- ✅ New: LLM-powered classification (70 lines)

### How It Works
```python
# Automatic classification
"scan nearby wifi" → LLM → "normal" ✅
"take my photo" → LLM → "normal" ✅
"research AI and write report" → LLM → "heavy" ✅
```

### Performance
- Instant tasks: 0ms (bypassed)
- Normal tasks (first): ~200-400ms
- Normal tasks (cached): 0ms

---

## WebAgent New Powers

### 1. scrape_structured
**Extract structured data from any webpage**

```python
# Extract tables
scrape_structured(url="https://example.com", extract="tables")

# Extract emails
scrape_structured(url="https://example.com", extract="emails")

# Extract links
scrape_structured(url="https://example.com", extract="links")
```

**Use:** "Get all rows from this table", "Find all emails on this page"

---

### 2. compare_search
**Side-by-side parallel research**

```python
compare_search(
    item_a="iPhone 15",
    item_b="Samsung S24",
    aspects=["price", "specs", "pros", "cons"]
)
```

**Use:** "Compare X vs Y", "Which is better X or Y"

---

### 3. web_monitor
**Track page changes**

```python
# Start monitoring
web_monitor(action="add", url="https://example.com", keyword="in stock")

# Check for changes
web_monitor(action="check")

# List monitored pages
web_monitor(action="list")
```

**Use:** "Tell me when this page changes", "Monitor this URL"

---

### 4. multi_search
**Parallel multi-query research**

```python
multi_search(
    queries=["best Python courses", "best JS courses", "best SQL courses"],
    fetch_top=2
)
```

**Use:** "Find best X, Y, and Z", "Research A, B, C"

---

### 5. fact_check
**Cross-source verification**

```python
fact_check(
    claim="Apple is the most valuable company",
    sources=4
)
```

**Returns:** Verdict (LIKELY TRUE / DISPUTED / UNVERIFIED) + confidence %

**Use:** "Is it true that...", "Fact check this claim"

---

### 6. search_reddit
**Reddit forum intelligence**

```python
search_reddit(
    query="best mechanical keyboards",
    subreddit="MechanicalKeyboards",  # optional
    max_posts=5
)
```

**Use:** "What does reddit think of X", "Reddit best Y"

---

### 7. search_stackoverflow
**Stack Overflow solutions**

```python
search_stackoverflow(
    query="how to fix Python ImportError",
    max_results=5
)
```

**Use:** "How to fix X error", "Stack Overflow Y solution"

---

### 8. image_search
**Web image search + download**

```python
image_search(
    query="Tesla Cybertruck",
    max_results=5,
    download=True  # downloads to Desktop
)
```

**Use:** "Find images of X", "Download logo of Y"

---

### 9. summarise_url
**TL;DR any link**

```python
# 5 styles available
summarise_url(url="https://example.com", style="bullets", max_bullets=5)
summarise_url(url="https://example.com", style="tldr")
summarise_url(url="https://example.com", style="eli5")
summarise_url(url="https://example.com", style="key_stats")
summarise_url(url="https://example.com", style="pros_cons")
```

**Use:** "Summarise this article", "TL;DR this page"

---

### 10. trending_topics
**What's hot right now**

```python
trending_topics(
    category="tech",  # general, tech, finance, sports, entertainment, science
    region="US"
)
```

**Returns:** Hacker News + Reddit + news aggregation

**Use:** "What's trending", "What's hot today"

---

### 11. web_to_dataset
**Research → Structured CSV/JSON**

```python
web_to_dataset(
    query="top AI companies 2024",
    columns=["Company", "Valuation", "Founded", "Product"],
    max_rows=20,
    output_format="json"
)
```

**Use:** "Build a table of X", "Make a spreadsheet of Y"

---

## Killer Combos

### Compare + Dataset + Excel
```
User: "Compare MacBook Air M3 vs Dell XPS 15 and save to Excel"
Chain: compare_search → web_to_dataset → FileAgent (.xlsx)
```

### Reddit + Compare
```
User: "What do people on Reddit think of Notion vs Obsidian"
Chain: search_reddit × 2 → compare_search
```

### Scrape + Dataset
```
User: "Get me a table of all S&P 500 companies from Wikipedia"
Chain: scrape_structured(extract='tables') → web_to_dataset
```

### Monitor + Cron
```
User: "Monitor this product page and tell me when it's back in stock"
Chain: web_monitor(action='add') + CronAgent
```

---

## Testing

### Quick Test
```bash
python test_llm_classifier.py
python test_webagent_powers.py
```

### Live Test
```
"compare iPhone 15 vs Samsung S24"
"what does reddit think of Python vs JavaScript"
"fact check: the earth is flat"
"what's trending on Hacker News"
"build a table of top 10 programming languages"
"summarise https://example.com/article"
"find images of Tesla Cybertruck"
"monitor https://example.com/product for changes"
```

---

## Key Stats

### LLM Classifier
- Code reduction: 73%
- Performance: 0ms (cached) to 400ms (first call)
- Maintenance: Zero

### WebAgent
- New powers: 10
- New dependencies: 0
- API keys required: 0
- Total tools: 69 (was 59)

---

## Documentation

- `COMPLETION_STATUS.md` — Overall status
- `LLM_CLASSIFIER_IMPLEMENTATION.md` — Classifier details
- `WEBAGENT_UPGRADE_COMPLETE.md` — WebAgent details
- `IMPLEMENTATION_SUMMARY.md` — Combined summary
- `test_llm_classifier.py` — Classifier tests
- `test_webagent_powers.py` — WebAgent tests

---

**Last Updated:** March 3, 2026  
**Status:** ✅ Production Ready
