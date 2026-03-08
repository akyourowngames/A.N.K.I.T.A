---
name: web-fetch
description: Fetch and read full content from a specific webpage or article
trigger: read page, fetch url, get full content, read article, extract from
---

## Steps

1. **Validate the URL**
   - Ensure user provided a valid URL
   - If they mentioned a page from search results, extract the URL
   - Confirm this is the right page to fetch

2. **Determine extraction type**
   - "main_content" (default) - Extract just the article/main content
   - "summary" - Get key points only (faster, less tokens)
   - "full" - Get entire page including sidebars, navigation, etc.
   - Choose based on what user needs

3. **Execute fetch with fetch_webpage tool**
   - Use fetch_webpage tool with the URL
   - Tool automatically handles:
     - Firecrawl API for clean extraction (~1,300ms)
     - Fallback to simple fetch if no API key
     - HTML stripping and markdown conversion
     - Content cleaning and formatting

4. **Process the content**
   - Review the extracted content
   - Identify the most relevant sections for user's question
   - Note the title and source URL

5. **Present relevant information**
   - Don't dump the entire page - extract what's relevant
   - Summarize key points that answer user's question
   - Include direct quotes only when necessary (max 30 words)
   - Always cite: [description](url)

6. **Offer follow-up**
   - Ask if they need specific sections explained
   - Offer to search for related information
   - Suggest saving important content to memory if relevant

## Rules

- ALWAYS cite the source URL
- Never reproduce more than 30 consecutive words verbatim
- Paraphrase and summarize rather than quote directly
- Don't fetch pages unnecessarily - use search_web first
- Only fetch when you need the FULL content, not just a snippet
- If page is very long (>10,000 chars), summarize key sections
- Add note: "Content rephrased for compliance with licensing restrictions"
- Respect robots.txt and rate limits
- If fetch fails, explain the error clearly
- Don't fetch from blocked domains (social media, forums, etc.)
