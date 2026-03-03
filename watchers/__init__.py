"""
Watchers package for A.N.K.I.T.A Watchdog System.

Exports all 4 watcher classes for use by WatchdogManager.
"""
from watchers.price_watcher import PriceWatcher
from watchers.news_watcher import NewsWatcher
from watchers.file_watcher import FileWatcher
from watchers.git_watcher import GitWatcher

__all__ = ["PriceWatcher", "NewsWatcher", "FileWatcher", "GitWatcher"]
