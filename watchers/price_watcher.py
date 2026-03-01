"""
PriceWatcher — Crypto & Stock Monitor for A.N.K.I.T.A.

Monitors asset prices via CoinGecko (crypto) and Yahoo Finance (stocks).
Alerts when user-defined threshold conditions are met.

Config (price_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 120,
        "cooldown_sec": 1800,
        "assets": [
            {
                "symbol": "bitcoin",
                "alert_conditions": [
                    {"type": "change_pct_below", "value": -5},
                    {"type": "price_above", "value": 100000}
                ]
            }
        ]
    }

Alert condition types:
    price_above         — alert when price > value
    price_below         — alert when price < value
    change_pct_above    — alert when 24h change % > value
    change_pct_below    — alert when 24h change % < value
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine


class PriceWatcher(BaseWatcher):
    """Monitors crypto and stock prices. Fires alerts on threshold breaches."""

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="PriceWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 120))
        self.cooldown_sec = float(config.get("cooldown_sec", 1800))

        # State keys:
        #   last_price[symbol]        — last known price
        #   last_alert_time[symbol]   — epoch of last alert (per asset)
        #   last_change_pct[symbol]   — last known 24h change %
        self.state.setdefault("last_price", {})
        self.state.setdefault("last_alert_time", {})
        self.state.setdefault("last_change_pct", {})

    def _check(self) -> Optional[str]:
        """Fetch prices for all configured assets and check alert conditions."""
        assets: List[Dict[str, Any]] = self.config.get("assets", [])
        if not assets:
            return None

        alerts: List[str] = []

        for asset in assets:
            symbol: str = asset.get("symbol", "").strip()
            conditions: List[Dict[str, Any]] = asset.get("alert_conditions", [])
            if not symbol or not conditions:
                continue

            price, change_pct = self._fetch_price(symbol)
            if price is None:
                print(f"[PriceWatcher] Could not fetch price for {symbol}", flush=True)
                continue

            print(
                f"[PriceWatcher] {symbol}: ${price:,.2f}  24h: {change_pct:+.2f}%",
                flush=True,
            )

            # Store latest values in state
            self.state["last_price"][symbol] = price
            self.state["last_change_pct"][symbol] = change_pct

            # Check cooldown
            last_alert = self.state["last_alert_time"].get(symbol, 0)
            if time.time() - last_alert < self.cooldown_sec:
                continue  # Still in cooldown window — skip alert

            # Evaluate each condition
            for cond in conditions:
                cond_type = cond.get("type", "")
                threshold = float(cond.get("value", 0))
                triggered = False
                msg = ""

                if cond_type == "price_above" and price > threshold:
                    triggered = True
                    msg = (
                        f"💰 {symbol.upper()} crossed ${threshold:,.0f}! "
                        f"Current price: ${price:,.2f}"
                    )
                elif cond_type == "price_below" and price < threshold:
                    triggered = True
                    msg = (
                        f"📉 {symbol.upper()} dropped below ${threshold:,.0f}! "
                        f"Current price: ${price:,.2f}"
                    )
                elif cond_type == "change_pct_above" and change_pct > threshold:
                    triggered = True
                    msg = (
                        f"🚀 {symbol.upper()} up {change_pct:+.2f}% in 24h! "
                        f"Price: ${price:,.2f}"
                    )
                elif cond_type == "change_pct_below" and change_pct < threshold:
                    triggered = True
                    msg = (
                        f"🔴 {symbol.upper()} down {change_pct:+.2f}% in 24h! "
                        f"Price: ${price:,.2f}"
                    )

                if triggered:
                    alerts.append(msg)
                    self.state["last_alert_time"][symbol] = time.time()
                    break  # One alert per asset per cycle

        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    def _fetch_price(self, symbol: str) -> tuple[Optional[float], float]:
        """
        Fetch current price and 24h change % for a symbol.

        Tries CoinGecko first (crypto), then Yahoo Finance (stocks).
        Uses the existing search_price() tool from tools.realtime_search.
        Falls back to direct HTTP if the tool isn't available.

        Returns:
            (price, change_pct) or (None, 0.0) on failure.
        """
        # Try the built-in search_price tool first
        try:
            from tools.realtime_search import search_price  # type: ignore
            result = search_price(symbol)
            if isinstance(result, dict) and result.get("ok"):
                price = result.get("price")
                change_pct = result.get("change_24h_pct", 0.0) or 0.0
                if price is not None:
                    return float(price), float(change_pct)
        except Exception as exc:
            print(f"[PriceWatcher] search_price tool failed: {exc}", flush=True)

        # Fallback: CoinGecko public API (no auth required)
        try:
            import urllib.request, json as _json
            cg_ids = {
                "bitcoin": "bitcoin", "btc": "bitcoin",
                "ethereum": "ethereum", "eth": "ethereum",
                "solana": "solana", "sol": "solana",
                "dogecoin": "dogecoin", "doge": "dogecoin",
                "bnb": "binancecoin", "xrp": "ripple",
            }
            cg_id = cg_ids.get(symbol.lower(), symbol.lower())
            url = (
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "ANKITA/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            if cg_id in data:
                entry = data[cg_id]
                price = float(entry.get("usd", 0))
                change = float(entry.get("usd_24h_change", 0) or 0)
                if price > 0:
                    return price, change
        except Exception as exc:
            print(f"[PriceWatcher] CoinGecko fallback failed for {symbol}: {exc}", flush=True)

        # Fallback: Yahoo Finance (for stocks)
        try:
            import urllib.request, json as _json
            ticker = symbol.upper()
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval=1d&range=2d"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            price = float(meta.get("regularMarketPrice", 0))
            prev = float(meta.get("chartPreviousClose", price) or price)
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            if price > 0:
                return price, change_pct
        except Exception as exc:
            print(f"[PriceWatcher] Yahoo Finance fallback failed for {symbol}: {exc}", flush=True)

        return None, 0.0
