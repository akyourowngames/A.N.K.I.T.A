---
name: web-search
description: Search the web and synthesize information into a structured summary
trigger: search web, search for, look up, find information, research, what is, find out
---

## Steps

1. **Identify search query and type**
   - Extract the core topic from user's message
   - Determine search type:
     - "news" for current events (5min cache)
     - "reference" for stable facts (24hr cache)
     - "general" for everything else (1hr cache)
   - Formulate a clear, specific search query

2. **Execute search with search_web tool**
   - Use search_web tool with the query
   - Tool automatically handles:
     - Cache checking (under 5ms if cached)
     - Brave Search API (669ms avg if not cached)
     - Source quality filtering (blocks low-quality domains)
     - Preferred source prioritization (Wikipedia, official docs, etc.)
   - Set max_results based on query complexity (3-5 typically)

3. **Analyze results**
   - Review the returned search results
   - Identify the most relevant sources (⭐ indicates preferred)
   - Note publication dates for time-sensitive queries
   - Check if results answer the question completely

4. **If more detail needed from specific source**
   - Use fetch_webpage tool to read full content
   - Only do this if search snippets are insufficient
   - Specify extract_type:
     - "main_content" for articles (default)
     - "summary" for quick overview
     - "full" for complete page

5. **Synthesize and present**
   - Combine information from multiple sources
   - Organize by topic/category if complex
   - Include inline citations: [description](url)
   - Highlight key takeaways
   - Add "Last updated" or publication dates when relevant

6. **Parallel searches for complex queries**
   - If query needs multiple perspectives, issue parallel searches:
     - Example: "compare X vs Y" → search "X benefits" + "Y benefits" simultaneously
   - All searches run in parallel (~700ms total, not 1400ms)
   - Combine results before synthesizing

## Rules

- ALWAYS cite sources with inline links [text](url)
- Never reproduce more than 30 consecutive words from a single source
- Paraphrase and summarize rather than quote directly
- Prioritize official documentation over blog posts
- Check publication dates - prefer recent sources for current topics
- If information conflicts between sources, note the discrepancy
- Add note: "Content rephrased for compliance with licensing restrictions"
- Use search_web for finding information, fetch_webpage for reading full articles
- Don't fetch full pages unless search snippets are insufficient
- For multiple related searches, call search_web multiple times in parallel
- Respect cache indicators - if result shows [cached], data is fresh enough
