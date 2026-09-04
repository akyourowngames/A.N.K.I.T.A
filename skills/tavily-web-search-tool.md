# Tavily Web Search Tool

Use this tool when the user asks to search online, look something up, check current information, compare recent facts, or answer anything likely to have changed.

Use it for current, recent, future, official, or likely-changing public facts, including:

- exam cutoffs, results, answer keys, admit cards, admissions, counselling, ranks, marks, and eligibility
- news, sports, schedules, releases, prices, market data, laws, rules, software versions, and product details
- official documentation, product pages, and source-backed comparisons
- anything where stale memory would be risky or where the user expects latest information

Tool arguments:

- `query`: preserve the user's key terms, dates, entity names, location, and requested context.
- `max_results`: use 3-5 for normal questions, more when comparison matters.
- `search_depth`: use `advanced` by default; `basic` only for quick/simple lookups.
- `topic`: use `news` for news/current-event queries; otherwise use `general`.
- `include_domains`: use when sir asks for official sources or a specific site/domain.
- `exclude_domains`: use to avoid unwanted source types.
- `days`: use with `topic=news` when sir asks for recent items.

Pro behavior:

- When a connected search tool is available, do not answer a likely-changing public-fact request by saying there is no real-time access. Search first.
- Prefer official or primary sources when the user asks for exact, current, technical, legal, medical, financial, or product information.
- For "latest", "today", "current", "2026", release dates, prices, cutoffs, ranks, and schedules, search before answering.
- Name or cite sources from the tool output in the final answer.
- If search fails because the API key is missing or the network is unavailable, say that plainly and do not invent results.
