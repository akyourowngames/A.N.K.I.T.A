"""A tiny real MCP stdio server used for end-to-end verification.

Run directly:  python tests/mcp_echo_server.py
Register:      zumba mcp add demo -- python tests/mcp_echo_server.py
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the given text back."""
    return f"echo: {text}"


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    mcp.run()
