"""Single source of truth for every MCP-layer tunable. Nothing is baked in:
override anything with an env var or (for the system note) a saved preference."""
import os


def _env(name: str, default: str) -> str:
    return (os.getenv(name, "") or default).strip()


# Names / formats
SEP = "__"                                   # tool namespacing separator (MCP spec)
META_SERVER = _env("ZUMBA_MCP_META_NAME", "zumba")   # virtual built-in server name

# Timeouts / limits
CONNECT_TIMEOUT = float(_env("ZUMBA_MCP_CONNECT_TIMEOUT", "15"))
TOOL_TIMEOUT = float(_env("ZUMBA_MCP_TOOL_TIMEOUT", "60"))
MAX_ITERATIONS = int(_env("ZUMBA_MCP_MAX_ITERATIONS", "25"))
SEARCH_LIMIT = int(_env("ZUMBA_MCP_SEARCH_LIMIT", "5"))
SEARCH_TIMEOUT = float(_env("ZUMBA_MCP_SEARCH_TIMEOUT", "20"))

# Registry
REGISTRY_URL = _env("ZUMBA_MCP_REGISTRY_URL", "https://registry.modelcontextprotocol.io/v0/servers")

# System-prompt note describing the meta-tools (overridable via env or the
# saved preference `mcp_system_note` in the config table).
SYSTEM_NOTE = _env(
    "ZUMBA_MCP_SYSTEM_NOTE",
    "You also have {meta}__mcp_search / {meta}__mcp_add / {meta}__mcp_remove / "
    "{meta}__mcp_list meta-tools to install or remove MCP servers on the fly — "
    "use them proactively when the user asks for a capability that needs a new server. "
    "mcp_search shows REGISTRY candidates (not connected); mcp_list is the only truth "
    "about what is connected — call it and quote it before answering status questions, "
    "and never present search results as installed servers.",
)
