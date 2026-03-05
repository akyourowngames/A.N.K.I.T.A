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

        # Per-alert cooldown — same alert cannot re-fire within this window.
        # Default 10 min (600s). Override via "cooldown_sec" in watcher JSON.
        self._alert_cooldown_sec: float = float(config.get("cooldown_sec", 600.0))
        # message fingerprint (first 80 chars) -> last_sent epoch
        self._alert_last_sent: dict = {}

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
        if "cooldown_sec" in new_config:
            self._alert_cooldown_sec = float(new_config["cooldown_sec"])

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
        """
        Push alert into ProactiveEngine queue with per-message cooldown.
        Uses first 80 chars as fingerprint so slight value changes share the bucket.
        """
        fingerprint = message[:80]
        now = time.time()
        if (now - self._alert_last_sent.get(fingerprint, 0.0)) < self._alert_cooldown_sec:
            return  # within cooldown window - suppress
        self._alert_last_sent[fingerprint] = now
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
        Auto-discover and load ALL watchers from the watchers/ package.

        Scans watchers/*.py for BaseWatcher subclasses, pairs each with its
        matching <name>_config.json, and instantiates enabled watchers.
        Safe to call multiple times (hot-updates existing configs).
        """
        discovered = self._discover_watcher_classes()

        for WatcherClass, config_name in discovered:
            config_file = self._config_dir / f"{config_name}.json"
            if not config_file.exists():
                self._write_default_config(config_name, WatcherClass)

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
                self._watchers[watcher_name].update_config(config)
            else:
                try:
                    watcher = WatcherClass(
                        config=config,
                        proactive=self.proactive,
                        workspace_root=self.workspace_root,
                    )
                    self._watchers[watcher_name] = watcher
                except Exception as exc:
                    print(f"[WatchdogManager] Failed to instantiate {watcher_name}: {exc}", flush=True)

        print(
            f"[WatchdogManager] {len(self._watchers)} watcher(s) loaded: "
            f"{list(self._watchers.keys())}",
            flush=True,
        )

    def _discover_watcher_classes(self) -> List[tuple]:
        """
        Auto-discover all BaseWatcher subclasses in the watchers/ package.

        Scans every *.py file in the watchers/ directory, imports it, and
        finds classes that inherit from BaseWatcher.

        Returns:
            List of (WatcherClass, config_name) tuples.
            config_name is derived from the class name:
                PriceWatcher  → price_config
                NewsWatcher   → news_config
                AppWatcher    → app_config
        """
        import importlib
        import inspect

        watchers_dir = Path(__file__).parent / "watchers"
        results: List[tuple] = []
        seen_names: set = set()

        for py_file in sorted(watchers_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"watchers.{py_file.stem}"
            try:
                mod = importlib.import_module(module_name)
            except Exception as exc:
                print(f"[WatchdogManager] Could not import {module_name}: {exc}", flush=True)
                continue

            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BaseWatcher)
                    and obj is not BaseWatcher
                    and obj.__name__ not in seen_names
                ):
                    seen_names.add(obj.__name__)
                    # Derive config name: "PriceWatcher" -> "price_config"
                    config_name = obj.__name__.lower().replace("watcher", "_config")
                    results.append((obj, config_name))
                    print(
                        f"[WatchdogManager] Discovered: {obj.__name__} -> {config_name}.json",
                        flush=True,
                    )

        return results

    def _write_default_config(self, config_name: str, watcher_class=None) -> None:
        """Write a sensible default config file so the user can customise it."""
        defaults: Dict[str, Any] = {
            "price_config": {
                "enabled": True,
                "poll_interval_sec": 120,
                "cooldown_sec": 1800,
                "portfolio_mode": False,
                "assets": [
                    {"symbol": "bitcoin",  "alert_conditions": [{"type": "change_pct_below", "value": -5}]},
                    {"symbol": "ethereum", "alert_conditions": [{"type": "change_pct_below", "value": -5}]},
                ],
            },
            "news_config": {
                "enabled": True,
                "poll_interval_sec": 600,
                "keywords": ["AI India", "artificial intelligence", "Helper ID"],
                "keyword_priorities": {},
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
                "watch_branches": [],
                "check_ci_status": False,
            },
            "network_config": {
                "enabled": True,
                "poll_interval_sec": 30,
                "ping_host": "8.8.8.8",
                "ping_timeout_sec": 3,
                "latency_alert_ms": 300,
                "check_vpn": True,
                "cooldown_sec": 120,
            },
            "disk_config": {
                "enabled": True,
                "poll_interval_sec": 300,
                "free_space_alert_pct": 10,
                "free_space_critical_pct": 5,
                "watch_paths": [],
                "track_growth": True,
                "growth_alert_mb_per_hour": 500,
                "cooldown_sec": 1800,
            },
            "battery_config": {
                "enabled": True,
                "poll_interval_sec": 60,
                "low_battery_pct": 20,
                "critical_battery_pct": 10,
                "overcharge_pct": 95,
                "alert_on_plug_unplug": True,
                "cooldown_sec": 300,
            },
            "calendar_config": {
                "enabled": False,
                "poll_interval_sec": 120,
                "alert_minutes_before": [10, 2],
                "calendar_ids": ["primary"],
                "credentials_file": "",
                "token_file": ".ankita/calendar_token.json",
                "local_tasks_file": ".ankita/tasks.json",
                "cooldown_sec": 60,
            },
            "email_config": {
                "enabled": False,
                "poll_interval_sec": 120,
                "max_results": 10,
                "vip_senders": [],
                "urgent_keywords": ["urgent", "asap", "deadline", "action required"],
                "label_filter": "INBOX",
                "credentials_file": "",
                "token_file": ".ankita/gmail_token.json",
                "cooldown_sec": 60,
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
        """Return a formatted health dashboard of all registered watchers."""
        if not self._watchers:
            return "No watchers registered."

        lines = ["🐕 Watchdog Health Dashboard", "═" * 60]
        total = len(self._watchers)
        running = sum(1 for w in self._watchers.values() if w.is_alive())
        lines.append(f"  Active: {running}/{total} watchers running\n")

        for name, watcher in self._watchers.items():
            alive = "✅" if watcher.is_alive() else "❌"
            poll = f"{watcher.poll_interval:.0f}s"

            # Crash history (from state if available)
            backoff = watcher._backoff
            backoff_str = f"  backoff={backoff:.0f}s" if backoff > 1.0 else ""

            # Last alert time (if watcher tracks it)
            last_alert_info = ""
            last_alert_map = watcher.state.get("last_alert_time", {})
            if last_alert_map:
                import time as _time
                most_recent = max(last_alert_map.values()) if last_alert_map else 0
                if most_recent:
                    secs_ago = int(_time.time() - most_recent)
                    if secs_ago < 3600:
                        last_alert_info = f"  last alert: {secs_ago}s ago"
                    else:
                        last_alert_info = f"  last alert: {secs_ago // 3600}h ago"

            lines.append(
                f"  {alive} {name:<22} poll={poll:<6}{backoff_str}{last_alert_info}"
            )

        lines.append("═" * 60)
        lines.append("  Tip: Edit .ankita/watchdogs/*.json to configure each watcher.")
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
