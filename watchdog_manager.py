"""
Watchdog Manager for A.N.K.I.T.A.

Provides always-on, self-healing background monitoring.
Watchers run in daemon threads and push alerts into ProactiveEngine._queue.

Architecture:
    WatchdogManager owns all watcher threads.
    BaseWatcher handles: lifecycle, crash recovery, state persistence, alert routing.
    Each watcher only overrides _check() — the single method that does real monitoring.

Usage (in chat.py / gui.py):
    from watchdog_manager import WatchdogManager
    watchdog_mgr = WatchdogManager(workspace_root=WORKSPACE_ROOT, proactive=proactive)
    watchdog_mgr.load_config()
    watchdog_mgr.start_all()
"""
from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from proactive import ProactiveEngine, ProactiveEvent


# ---------------------------------------------------------------------------
# Singleton registry — lets the orchestrator find the running WatchdogManager
# ---------------------------------------------------------------------------

_INSTANCE: "Optional[WatchdogManager]" = None


def register_instance(mgr: "WatchdogManager") -> None:
    """Register the active WatchdogManager so the orchestrator can reach it."""
    global _INSTANCE
    _INSTANCE = mgr


def get_instance() -> "Optional[WatchdogManager]":
    """Return the running WatchdogManager instance, or None if not started."""
    return _INSTANCE


# ---------------------------------------------------------------------------
# BaseWatcher — the self-healing daemon core
# ---------------------------------------------------------------------------

class BaseWatcher(ABC):
    """
    Abstract base class for all ANKITA watchdogs.

    Subclasses must override _check() — the single method that performs
    the actual monitoring logic and returns an alert string (or None).

    Everything else — threading, crash recovery, state persistence,
    alert routing — is handled here.
    """

    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        self.name = name
        self.config = config
        self.proactive = proactive
        self.workspace_root = workspace_root

        # Thread control
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Crash recovery — exponential backoff
        self._backoff: float = 1.0       # seconds, doubles on each crash
        self._max_backoff: float = 300.0  # cap at 5 minutes

        # State persistence — survives ANKITA restarts
        self._state_dir = workspace_root / ".ankita" / "watchdogs" / "state"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / f"{name.lower()}_state.json"
        self.state: Dict[str, Any] = self._load_state()

        # Poll interval (seconds) — subclass config may override
        self.poll_interval: float = float(config.get("poll_interval_sec", 60.0))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the daemon watcher thread."""
        if self._thread is not None and self._thread.is_alive():
            print(f"[{self.name}] Already running — skip.", flush=True)
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=self.name
        )
        self._thread.start()
        print(f"[{self.name}] Started. Poll: {self.poll_interval}s", flush=True)

    def stop(self) -> None:
        """Signal the watcher to stop and wait for thread to exit."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval + 5)
        print(f"[{self.name}] Stopped.", flush=True)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """Hot-update config without restarting the watcher."""
        self.config.update(new_config)
        if "poll_interval_sec" in new_config:
            self.poll_interval = float(new_config["poll_interval_sec"])

    # ------------------------------------------------------------------
    # Abstract method — subclasses implement this
    # ------------------------------------------------------------------

    @abstractmethod
    def _check(self) -> Optional[str]:
        """
        Perform one monitoring check.

        Returns:
            Alert message string if something noteworthy happened, else None.
        Raises:
            Any exception — BaseWatcher will catch it and apply backoff.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Alert routing
    # ------------------------------------------------------------------

    def _alert(self, message: str, kind: str = "watchdog") -> None:
        """Push an alert into ProactiveEngine's queue for display in GUI/chat."""
        event = ProactiveEvent(kind=kind, message=message, data={"watcher": self.name})
        self.proactive._queue.put(event)
        print(f"[{self.name}] 🚨 ALERT: {message[:100]}", flush=True)

    # ------------------------------------------------------------------
    # Self-healing run loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main daemon loop — calls _check() at poll_interval, recovers from crashes."""
        print(f"[{self.name}] Loop started.", flush=True)
        while not self._stop.is_set():
            try:
                alert = self._check()
                if alert:
                    self._alert(alert)
                self._backoff = 1.0  # reset backoff on success
            except Exception as exc:
                print(
                    f"[{self.name}] CRASH: {exc!r} — retrying in {self._backoff:.0f}s",
                    flush=True,
                )
                self._stop.wait(self._backoff)
                self._backoff = min(self._backoff * 2, self._max_backoff)
                continue

            # Normal sleep: interruptible by stop()
            self._stop.wait(self.poll_interval)

        print(f"[{self.name}] Loop exited.", flush=True)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        """Load persisted state from disk (survives ANKITA restarts)."""
        try:
            if self._state_file.exists():
                return json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[{self.name}] State load failed: {exc}", flush=True)
        return {}

    def _save_state(self) -> None:
        """Persist current state to disk."""
        try:
            self._state_file.write_text(
                json.dumps(self.state, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            print(f"[{self.name}] State save failed: {exc}", flush=True)


# ---------------------------------------------------------------------------
# WatchdogManager — owns and coordinates all watchers
# ---------------------------------------------------------------------------

class WatchdogManager:
    """
    Singleton-style manager that owns all ANKITA watchdog threads.

    Usage:
        mgr = WatchdogManager(workspace_root=WORKSPACE_ROOT, proactive=proactive)
        mgr.load_config()   # reads .ankita/watchdogs/*.json
        mgr.start_all()     # spawns daemon threads
        ...
        mgr.stop_all()      # on shutdown
    """

    def __init__(self, workspace_root: Path, proactive: ProactiveEngine) -> None:
        self.workspace_root = workspace_root
        self.proactive = proactive
        self._watchers: Dict[str, BaseWatcher] = {}
        self._config_dir = workspace_root / ".ankita" / "watchdogs"
        self._config_dir.mkdir(parents=True, exist_ok=True)
        # Register this instance so the orchestrator can reach it
        register_instance(self)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def load_config(self) -> None:
        """
        Load watcher configs from .ankita/watchdogs/*.json and instantiate watchers.
        Safe to call multiple times (re-registers changed configs).
        """
        from watchers import PriceWatcher, NewsWatcher, FileWatcher, GitWatcher

        watcher_classes = {
            "price_config": PriceWatcher,
            "news_config":  NewsWatcher,
            "file_config":  FileWatcher,
            "git_config":   GitWatcher,
        }

        for config_name, WatcherClass in watcher_classes.items():
            config_file = self._config_dir / f"{config_name}.json"
            if not config_file.exists():
                # Write default config so user can edit it
                self._write_default_config(config_name)

            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[WatchdogManager] Failed to load {config_file}: {exc}", flush=True)
                config = {}

            # Skip disabled watchers
            if not config.get("enabled", True):
                print(f"[WatchdogManager] {config_name} disabled — skipping.", flush=True)
                continue

            watcher_name = WatcherClass.__name__
            if watcher_name in self._watchers:
                # Hot-update existing watcher config
                self._watchers[watcher_name].update_config(config)
            else:
                watcher = WatcherClass(
                    config=config,
                    proactive=self.proactive,
                    workspace_root=self.workspace_root,
                )
                self._watchers[watcher_name] = watcher

        print(
            f"[WatchdogManager] {len(self._watchers)} watcher(s) loaded: "
            f"{list(self._watchers.keys())}",
            flush=True,
        )

    def _write_default_config(self, config_name: str) -> None:
        """Write a sensible default config file so the user can customise it."""
        defaults: Dict[str, Any] = {
            "price_config": {
                "enabled": True,
                "poll_interval_sec": 120,
                "cooldown_sec": 1800,
                "assets": [
                    {"symbol": "bitcoin",  "alert_conditions": [{"type": "change_pct_below", "value": -5}]},
                    {"symbol": "ethereum", "alert_conditions": [{"type": "change_pct_below", "value": -5}]},
                ],
            },
            "news_config": {
                "enabled": True,
                "poll_interval_sec": 600,
                "keywords": ["AI India", "artificial intelligence", "Helper ID"],
            },
            "file_config": {
                "enabled": True,
                "poll_interval_sec": 30,
                "watch_dirs": [
                    str(Path.home() / "Desktop"),
                    str(Path.home() / "Downloads"),
                ],
                "auto_summarise_pdf": True,
            },
            "git_config": {
                "enabled": False,
                "poll_interval_sec": 300,
                "repos": [],
                "github_token_env": "GITHUB_TOKEN",
            },
        }
        default = defaults.get(config_name, {"enabled": False})
        config_file = self._config_dir / f"{config_name}.json"
        try:
            config_file.write_text(
                json.dumps(default, indent=2), encoding="utf-8"
            )
            print(f"[WatchdogManager] Created default config: {config_file}", flush=True)
        except Exception as exc:
            print(f"[WatchdogManager] Could not write default config: {exc}", flush=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def register(self, watcher: BaseWatcher) -> None:
        """Register a custom watcher (e.g. from WatchdogAgent)."""
        self._watchers[watcher.name] = watcher

    def unregister(self, name: str) -> None:
        """Stop and remove a watcher by name."""
        watcher = self._watchers.pop(name, None)
        if watcher:
            watcher.stop()

    def start_all(self) -> None:
        """Start all registered watchers."""
        for watcher in self._watchers.values():
            try:
                watcher.start()
            except Exception as exc:
                print(f"[WatchdogManager] Failed to start {watcher.name}: {exc}", flush=True)

    def stop_all(self) -> None:
        """Stop all watchers gracefully."""
        for watcher in self._watchers.values():
            try:
                watcher.stop()
            except Exception as exc:
                print(f"[WatchdogManager] Error stopping {watcher.name}: {exc}", flush=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> str:
        """Return a formatted status table of all registered watchers."""
        if not self._watchers:
            return "No watchers registered."
        lines = ["🐕 Watchdog Status:", "─" * 40]
        for name, watcher in self._watchers.items():
            alive = "✅ Running" if watcher.is_alive() else "❌ Stopped"
            poll = f"{watcher.poll_interval:.0f}s"
            lines.append(f"  {name:<20} {alive}  (poll: {poll})")
        lines.append("─" * 40)
        return "\n".join(lines)

    def add_price_alert(self, symbol: str, condition_type: str, value: float) -> str:
        """
        Convenience: add a price alert for an asset.
        Called by WatchdogAgent when user says 'alert me if BTC drops 5%'.
        """
        config_file = self._config_dir / "price_config.json"
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            config = {"enabled": True, "poll_interval_sec": 120, "cooldown_sec": 1800, "assets": []}

        assets = config.setdefault("assets", [])
        # Find or create asset entry
        asset_entry = next((a for a in assets if a.get("symbol", "").lower() == symbol.lower()), None)
        if asset_entry is None:
            asset_entry = {"symbol": symbol.lower(), "alert_conditions": []}
            assets.append(asset_entry)

        asset_entry["alert_conditions"].append({"type": condition_type, "value": value})
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Hot-update the running watcher
        pw = self._watchers.get("PriceWatcher")
        if pw:
            pw.update_config(config)

        return f"✅ Price alert set: {symbol} {condition_type} {value}"

    def add_news_keyword(self, keyword: str) -> str:
        """Convenience: add a news tracking keyword."""
        config_file = self._config_dir / "news_config.json"
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            config = {"enabled": True, "poll_interval_sec": 600, "keywords": []}

        keywords = config.setdefault("keywords", [])
        if keyword not in keywords:
            keywords.append(keyword)
            config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
            nw = self._watchers.get("NewsWatcher")
            if nw:
                nw.update_config(config)
            return f"✅ Now tracking news for: '{keyword}'"
        return f"ℹ️ Already tracking '{keyword}'"

    def add_watch_dir(self, directory: str) -> str:
        """Convenience: add a directory to FileWatcher."""
        config_file = self._config_dir / "file_config.json"
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            config = {"enabled": True, "poll_interval_sec": 30, "watch_dirs": []}

        dirs = config.setdefault("watch_dirs", [])
        if directory not in dirs:
            dirs.append(directory)
            config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
            fw = self._watchers.get("FileWatcher")
            if fw:
                fw.update_config(config)
            return f"✅ Now watching directory: {directory}"
        return f"ℹ️ Already watching: {directory}"

    def add_git_repo(self, repo_path: str) -> str:
        """Convenience: add a git repository to GitWatcher."""
        config_file = self._config_dir / "git_config.json"
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            config = {
                "enabled": True,
                "poll_interval_sec": 300,
                "repos": [],
                "github_token_env": "GITHUB_TOKEN",
            }

        # Enable the watcher if it was disabled
        config["enabled"] = True
        repos = config.setdefault("repos", [])
        if repo_path not in repos:
            repos.append(repo_path)
            config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

            # If GitWatcher not yet running, instantiate and start it
            gw = self._watchers.get("GitWatcher")
            if gw is None:
                try:
                    from watchers.git_watcher import GitWatcher  # type: ignore
                    gw = GitWatcher(
                        config=config,
                        proactive=self.proactive,
                        workspace_root=self.workspace_root,
                    )
                    self._watchers["GitWatcher"] = gw
                    gw.start()
                except Exception as exc:
                    return f"⚠️ GitWatcher could not start: {exc}"
            else:
                gw.update_config(config)
            return f"✅ Now monitoring git repo: {repo_path}"
        return f"ℹ️ Already monitoring: {repo_path}"
