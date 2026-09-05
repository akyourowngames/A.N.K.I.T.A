"""Async MCP connection manager.

Connects to every enabled MCP server (stdio subprocess, streamable HTTP or SSE),
collects their tools into a namespaced registry, and executes tool calls.
A failing server never crashes the chat — it degrades to 'offline' status.
"""
import asyncio
import json
import os
import time
from typing import Any, Optional

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    try:
        from mcp.client.sse import sse_client
    except Exception:
        sse_client = None
    MCP_SDK = True
except Exception:
    MCP_SDK = False

from mcpclient import defaults
from mcpclient.config import list_servers
import mcpclient.tools as mt


class ServerState:
    def __init__(self, name: str, entry: dict):
        self.name = name
        self.entry = entry
        self.status = "pending"  # pending | online | offline | disabled
        self.error: str = ""
        self.tools: list = []          # MCP Tool objects
        self.session: Any = None
        self._ctx_stack: Any = None
        self._task: Any = None
        self._ready: Any = None
        self.connected_at: float = 0.0

    def transport(self) -> str:
        return str(self.entry.get("transport", "stdio"))

    def summary(self) -> dict:
        return {
            "name": self.name,
            "transport": self.transport(),
            "status": self.status,
            "error": self.error,
            "tool_count": len(self.tools),
            "tools": [getattr(t, "name", str(t)) for t in self.tools],
        }


class MCPManager:
    """Owns connections to all enabled MCP servers. Pure asyncio; run its
    methods from a background thread/loop in the sync chat CLI."""

    def __init__(self, config: Optional[dict] = None, connect_timeout: Optional[float] = None):
        self.config = config if config is not None else list_servers()
        self.servers: dict[str, ServerState] = {}
        self.connect_timeout = connect_timeout if connect_timeout is not None else defaults.CONNECT_TIMEOUT
        self.meta_state: dict = {}   # per-instance state for built-in meta-tools
        try:
            self._loaded_mtime = self._files_mtime()
        except Exception:
            self._loaded_mtime = (0.0, 0.0)

    async def start(self) -> None:
        for name, entry in self.config.items():
            if not entry.get("enabled", True):
                st = ServerState(name, entry)
                st.status = "disabled"
                self.servers[name] = st
                continue
            self.servers[name] = ServerState(name, entry)
            await self._connect(self.servers[name])

    async def stop(self) -> None:
        for st in list(self.servers.values()):
            await self._close(st)

    async def _close(self, st: ServerState) -> None:
        """Cancel the connection's own task so anyio cancel scopes exit in
        the same task that entered them."""
        task = getattr(st, "_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        st.session = None
        st._task = None

    async def _open_and_serve(self, st: ServerState) -> None:
        """Runs in a dedicated task: opens transport + session, collects tools,
        then parks until cancelled (cleanup happens inside this same task)."""
        import contextlib
        entry = st.entry
        try:
            async with contextlib.AsyncExitStack() as stack:
                if st.transport() == "stdio":
                    env = dict(os.environ)
                    env.update({str(k): str(v) for k, v in (entry.get("env") or {}).items()})
                    params = StdioServerParameters(
                        command=str(entry["command"]),
                        args=[str(a) for a in (entry.get("args") or [])],
                        env=env,
                        cwd=entry.get("cwd") or None,
                    )
                    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
                elif st.transport() == "http":
                    headers = {str(k): str(v) for k, v in (entry.get("headers") or {}).items()}
                    opened = await stack.enter_async_context(
                        streamablehttp_client(str(entry["url"]), headers=headers or None))
                    read_stream, write_stream = opened[0], opened[1]
                elif st.transport() == "sse" and sse_client is not None:
                    headers = {str(k): str(v) for k, v in (entry.get("headers") or {}).items()}
                    opened = await stack.enter_async_context(
                        sse_client(str(entry["url"]), headers=headers or None))
                    read_stream, write_stream = opened[0], opened[1]
                else:
                    st.status = "offline"
                    st.error = f"unsupported transport '{st.transport()}'"
                    return
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await asyncio.wait_for(session.initialize(), timeout=self.connect_timeout)
                result = await session.list_tools()
                st.session = session
                st.tools = list(getattr(result, "tools", []) or [])
                st.status = "online"
                st.error = ""
                st.connected_at = time.time()
                st._ready.set()
                await asyncio.Event().wait()  # parked; cancelled by _close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            st.status = "offline"
            st.error = str(exc)[:300]
        finally:
            st._ready.set()
            st.session = None

    async def _connect(self, st: ServerState) -> None:
        if not MCP_SDK:
            st.status = "offline"
            st.error = "mcp package not installed"
            st._ready.set()
            return
        st._ready = asyncio.Event()
        st.status = "pending"
        st.error = ""
        st._task = asyncio.get_running_loop().create_task(self._open_and_serve(st))
        try:
            await asyncio.wait_for(st._ready.wait(), timeout=self.connect_timeout)
        except asyncio.TimeoutError:
            st.status = "offline"
            st.error = f"connection timed out after {self.connect_timeout:.0f}s"
            await self._close(st)

    async def reconnect(self, name: str) -> ServerState:
        st = self.servers.get(name)
        if st is None:
            entry = self.config.get(name)
            if entry is None:
                raise KeyError(name)
            st = ServerState(name, entry)
            self.servers[name] = st
        if st.status == "disabled":
            return st
        await self._close(st)
        await self._connect(st)
        return st

    # ---- hot reload ------------------------------------------------------
    def _config_signature(self, config: dict) -> dict:
        return {k: json.dumps(v, sort_keys=True) for k, v in config.items()}

    def _files_mtime(self) -> tuple:
        from mcpclient.config import home_config_path, project_config_path
        mtimes = []
        for p in (home_config_path(), project_config_path()):
            try:
                mtimes.append(p.stat().st_mtime)
            except OSError:
                mtimes.append(0.0)
        return tuple(mtimes)

    def stale(self) -> bool:
        """True if mcp.json changed on disk since the last (re)load."""
        return self._files_mtime() != self._loaded_mtime

    async def reload(self, config: Optional[dict] = None) -> dict:
        """Diff config vs running servers: start new, stop removed, reconnect
        changed. Everything happens live — no restart needed."""
        from mcpclient.config import list_servers as _list
        new_config = config if config is not None else _list()
        old_sig = self._config_signature(self.config)
        new_sig = self._config_signature(new_config)
        summary = {"added": [], "removed": [], "updated": [], "unchanged": 0}
        if old_sig == new_sig and not self.stale():
            summary["unchanged"] = len(new_config)
            for name, entry in new_config.items():
                st = self.servers.get(name)
                if (st is not None and entry.get("enabled", True)
                        and st.status not in ("online", "disabled", "pending")):
                    st.entry = entry
                    await self._connect(st)
                    summary["updated"].append(f"{name} (retry)")
            return summary
        # removed / disabled servers
        for name in list(self.servers.keys()):
            was = self.config.get(name, {})
            now = new_config.get(name)
            if now is None:
                await self._close(self.servers[name])
                del self.servers[name]
                summary["removed"].append(name)
                continue
            if not now.get("enabled", True) and self.servers[name].status != "disabled":
                await self._close(self.servers[name])
                self.servers[name].status = "disabled"
                self.servers[name].entry = now
                summary["updated"].append(name)
                continue
            if json.dumps(was, sort_keys=True) != json.dumps(now, sort_keys=True):
                st = self.servers[name]
                st.entry = now
                if now.get("enabled", True):
                    await self._connect(st)
                summary["updated"].append(name)
                continue
            if now.get("enabled", True) and self.servers[name].status not in ("online", "disabled", "pending"):
                await self._connect(self.servers[name])
                summary["updated"].append(f"{name} (retry)")
        # new servers
        for name, entry in new_config.items():
            if name in self.servers:
                continue
            st = ServerState(name, entry)
            if not entry.get("enabled", True):
                st.status = "disabled"
            else:
                self.servers[name] = st
                await self._connect(st)
                summary["added"].append(name)
                continue
            self.servers[name] = st
        self.config = new_config
        self._loaded_mtime = self._files_mtime()
        return summary

    # ---- queries ---------------------------------------------------------
    def all_tools(self) -> list:
        """Namespaced OpenAI-format tools for every online server + built-ins."""
        out = []
        for st in self.servers.values():
            if st.status == "online":
                out.extend(mt.mcp_tools_to_openai(st.name, st.tools))
        from mcpclient import builtin
        out.extend(builtin.visible_tools())
        return out

    def online_count(self) -> int:
        return sum(1 for s in self.servers.values() if s.status == "online")

    def status_rows(self) -> list:
        return [st.summary() for st in self.servers.values()]

    # ---- execution -------------------------------------------------------
    async def call_tool(self, qualified_name: str, arguments: dict, timeout: Optional[float] = None) -> str:
        timeout = timeout if timeout is not None else defaults.TOOL_TIMEOUT
        server, _, tool = qualified_name.partition(mt.SEP)
        if server == defaults.META_SERVER:
            from mcpclient import builtin
            return await builtin.handle(self, tool, arguments)
        split = mt.split_qualified(qualified_name)
        if split is None:
            return f"ERROR: unknown tool '{qualified_name}' (expected server__tool format)."
        server, tool = split
        st = self.servers.get(server)
        if st is None:
            return f"ERROR: MCP server '{server}' is not configured."
        if st.status == "disabled":
            return f"ERROR: MCP server '{server}' is disabled."
        if st.status != "online" or st.session is None:
            st = await self.reconnect(server)
        if st.status != "online" or st.session is None:
            return f"ERROR: MCP server '{server}' is offline ({st.error or 'connection failed'})."
        try:
            result = await asyncio.wait_for(
                st.session.call_tool(tool, arguments=arguments or {}), timeout=timeout
            )
            return mt.tool_result_text(result) or "(tool returned no content)"
        except asyncio.TimeoutError:
            return f"ERROR: tool '{tool}' timed out after {timeout:.0f}s."
        except Exception as exc:
            return f"ERROR: tool '{tool}' failed: {str(exc)[:300]}"


# ---- sync bridge for the CLI ------------------------------------------------
_loop: Optional[asyncio.AbstractEventLoop] = None
_mgr: Optional[MCPManager] = None


def manager() -> MCPManager:
    """Get (or lazily create and start) the global MCP manager. Returns an
    empty offline manager on failure — chat must never crash because of MCP."""
    global _loop, _mgr
    try:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _mgr = None
        if _mgr is None:
            _mgr = MCPManager()
            _loop.run_until_complete(_mgr.start())
        return _mgr
    except Exception as exc:  # noqa: BLE001
        fallback = MCPManager(config={})
        fallback._start_error = str(exc)
        return fallback


def run_tool(qualified_name: str, arguments: dict, timeout: Optional[float] = None) -> str:
    mgr = manager()
    return _loop.run_until_complete(mgr.call_tool(qualified_name, arguments, timeout=timeout))


def reload_sync(mgr: Optional[MCPManager] = None) -> dict:
    """Live-reload servers from disk config (start new / stop removed)."""
    mgr = mgr or manager()
    return _loop.run_until_complete(mgr.reload())


def reload_if_stale_sync(mgr: Optional[MCPManager] = None) -> Optional[dict]:
    """Cheap check: reload only if an mcp.json changed on disk."""
    mgr = mgr or manager()
    try:
        if mgr.stale():
            return reload_sync(mgr)
    except Exception:
        return None
    return None


def shutdown() -> None:
    global _loop, _mgr
    try:
        if _loop is not None and not _loop.is_closed() and _mgr is not None:
            try:
                _loop.run_until_complete(_mgr.stop())
            except BaseException:
                pass
            try:
                _loop.close()
            except BaseException:
                pass
    except BaseException:
        pass
    _loop = None
    _mgr = None
