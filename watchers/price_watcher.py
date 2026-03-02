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

# Max age of the CoinGecko coin-ID cache before we force a refresh (12h).
# The cache file is written by tools/realtime_search.py.
# If it's older than this, we delete it on startup so the next price fetch
# automatically pulls a fresh coin list — preventing stale/wrong coin ID mappings.
_COIN_CACHE_MAX_AGE_SEC = 12 * 3600  # 12 hours


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
        #   last_error[symbol]        — last fetch error message (for diagnostics)
        self.state.setdefault("last_price", {})
        self.state.setdefault("last_alert_time", {})
        self.state.setdefault("last_change_pct", {})
        self.state.setdefault("last_error", {})

        # Clear stale CoinGecko coin ID cache on startup to prevent wrong price lookups.
        self._clear_stale_coin_cache(workspace_root)

    def _clear_stale_coin_cache(self, workspace_root: Path) -> None:
        """
        Delete the CoinGecko coin-ID cache file if it's older than 12 hours.

        The cache (.coingecko_coins.json) is written by tools/realtime_search.py
        and is valid for 24h by default. If stale, coin ID mappings become wrong
        (e.g. a renamed or replaced token), causing zero or incorrect prices.

        We cut this to 12h to catch daily shifts in the CoinGecko listing order.
        """
        # The cache lives alongside realtime_search.py in the tools/ folder
        cache_candidates = [
            workspace_root / "tools" / ".coingecko_coins.json",
            Path(__file__).parent.parent / "tools" / ".coingecko_coins.json",
        ]
        for cache_path in cache_candidates:
            if cache_path.exists():
                try:
                    age_sec = time.time() - cache_path.stat().st_mtime
                    if age_sec > _COIN_CACHE_MAX_AGE_SEC:
                        cache_path.unlink()
                        print(
                            f"[PriceWatcher] 🗑️  Cleared stale CoinGecko cache "
                            f"({age_sec/3600:.1f}h old > {_COIN_CACHE_MAX_AGE_SEC/3600:.0f}h limit): "
                            f"{cache_path}",
                            flush=True,
                        )
                    else:
                        print(
                            f"[PriceWatcher] ✅ CoinGecko cache is fresh "
                            f"({age_sec/3600:.1f}h old, limit {_COIN_CACHE_MAX_AGE_SEC/3600:.0f}h)",
                            flush=True,
                        )
                except Exception as e:
                    print(f"[PriceWatcher] ⚠️  Could not check coin cache: {e}", flush=True)
                return  # Only process the first found cache file

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
                err_msg = f"All price sources failed for '{symbol}' — check symbol spelling or network"
                print(f"[PriceWatcher] ❌ {err_msg}", flush=True)
                self.state["last_error"][symbol] = {
                    "time": time.time(),
                    "msg": err_msg,
                }
                self._save_state()
                continue
            # Clear any previous error now that we have a valid price
            self.state["last_error"].pop(symbol, None)

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

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        """
        Normalise a price symbol before passing to search_price().

        Users often type symbols with suffixes like BTC-USD, ETH-USDT, AAPL.NS
        which confuse CoinGecko's coin-ID lookup. Strip common suffixes and
        map obvious aliases to canonical CoinGecko IDs.

        Examples:
            "BTC-USD"   → "bitcoin"
            "ETH-USDT"  → "ethereum"
            "SOL"       → "solana"
            "AAPL"      → "AAPL"   (stocks left as-is — Yahoo Finance handles them)
        """
        _ALIASES: Dict[str, str] = {
            "btc": "bitcoin", "bitcoin": "bitcoin",
            "eth": "ethereum", "ethereum": "ethereum",
            "sol": "solana", "solana": "solana",
            "doge": "dogecoin", "dogecoin": "dogecoin",
            "bnb": "binancecoin", "binancecoin": "binancecoin",
            "xrp": "ripple", "ripple": "ripple",
            "ada": "cardano", "cardano": "cardano",
            "dot": "polkadot", "polkadot": "polkadot",
            "matic": "matic-network", "polygon": "matic-network",
            "avax": "avalanche-2", "avalanche": "avalanche-2",
            "link": "chainlink", "chainlink": "chainlink",
            "uni": "uniswap", "uniswap": "uniswap",
            "atom": "cosmos", "cosmos": "cosmos",
            "ltc": "litecoin", "litecoin": "litecoin",
            "shib": "shiba-inu", "shiba": "shiba-inu",
            "trx": "tron", "tron": "tron",
            "near": "near", "algo": "algorand",
            "xlm": "stellar", "stellar": "stellar",
            "icp": "internet-computer",
            "apt": "aptos", "aptos": "aptos",
            "sui": "sui", "arb": "arbitrum",
        }
        # Strip common quote suffixes: BTC-USD → btc, ETH-USDT → eth, SOL-BTC → sol
        s = symbol.strip()
        for suffix in ("-USD", "-USDT", "-BTC", "-ETH", "-BUSD", ".NS", ".BO"):
            if s.upper().endswith(suffix):
                s = s[: -len(suffix)]
                break
        return _ALIASES.get(s.lower(), s)

    def _fetch_price(self, symbol: str) -> tuple[Optional[float], float]:
        """
        Fetch current price and 24h change % for a symbol.

        Strategy (in order):
          1. Normalise the symbol (strip -USD/-USDT suffixes, map aliases)
          2. search_price() tool — has CoinGecko + Yahoo + web fallback chain
          3. If tool import fails, direct CoinGecko HTTP call (crypto only)
          4. Direct Yahoo Finance HTTP call (stocks)

        Returns:
            (price, change_pct) or (None, 0.0) on all failures.
        """
        # Step 1: Normalise symbol — avoids "BTC-USD" being passed verbatim to CoinGecko
        normalised = self._normalise_symbol(symbol)
        if normalised != symbol:
            print(f"[PriceWatcher] 🔄 Normalised symbol '{symbol}' → '{normalised}'", flush=True)

        # Step 2: search_price() tool (preferred — handles crypto + stocks + web)
        for query in ([normalised, symbol] if normalised != symbol else [normalised]):
            try:
                from tools.realtime_search import search_price  # type: ignore
                result = search_price(query)
                if isinstance(result, dict) and result.get("ok"):
                    price = result.get("price")
                    change_pct = result.get("change_24h_pct", 0.0) or 0.0
                    if price is not None and float(price) > 0:
                        return float(price), float(change_pct)
            except Exception as exc:
                print(f"[PriceWatcher] search_price('{query}') failed: {exc}", flush=True)
                break  # Don't retry on import error

        # Step 3: Direct CoinGecko fallback (crypto)
        try:
            import urllib.request, json as _json
            cg_id = normalised.lower()
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
            else:
                print(f"[PriceWatcher] CoinGecko: '{cg_id}' not found in response", flush=True)
        except Exception as exc:
            print(f"[PriceWatcher] CoinGecko fallback failed for '{normalised}': {exc}", flush=True)

        # Step 4: Yahoo Finance fallback (stocks + some crypto pairs)
        try:
            import urllib.request, json as _json
            # For stocks use original symbol; for crypto try the normalised version
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
            print(f"[PriceWatcher] Yahoo Finance fallback failed for '{symbol}': {exc}", flush=True)

        return None, 0.0
