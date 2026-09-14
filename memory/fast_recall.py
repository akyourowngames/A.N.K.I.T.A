"""Local chat history only; no graph fallback, cache, queue or model call."""


def recall(query="", budget=None, *, exclude_session=""):
    from memory import get_memory
    return get_memory().recall(query, max_bytes=4000, exclude_session=exclude_session)


def local_context(query=""):
    return recall(query)
