"""Free candle data from Deriv's public WebSocket (no login, no key)."""
import asyncio
import json
import re

import pandas as pd
import websockets

ENDPOINTS = [
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id=1089",  # older endpoint, used as backup
]
GRANULARITY = {"D1": 86400, "H4": 14400, "H1": 3600, "M15": 900}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _to_df(candles) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    if df.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["epoch"].astype(int), unit="s", utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close"]]


class Feed:
    """One connection reused for every request in a run."""

    def __init__(self):
        self.ws = None
        self.url = None
        self._req = 0

    async def __aenter__(self):
        last = None
        for url in ENDPOINTS:
            try:
                self.ws = await websockets.connect(url, open_timeout=20, max_size=2 ** 24)
                self.url = url
                return self
            except Exception as e:  # try the next endpoint
                last = e
        raise RuntimeError(f"Could not reach Deriv price feed: {last}")

    async def __aexit__(self, *exc):
        if self.ws:
            await self.ws.close()

    async def call(self, payload: dict, retries: int = 3) -> dict:
        for attempt in range(retries):
            self._req += 1
            rid = self._req
            await self.ws.send(json.dumps({**payload, "req_id": rid}))
            while True:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
                if msg.get("req_id") == rid:
                    break
            err = msg.get("error")
            if err and "rate" in str(err.get("code", "")).lower() + str(err.get("message", "")).lower():
                await asyncio.sleep(2 * (attempt + 1))
                continue
            return msg
        return msg

    async def symbols(self) -> list:
        msg = await self.call({"active_symbols": "brief"})
        if "error" in msg:
            raise RuntimeError(msg["error"].get("message"))
        return msg.get("active_symbols", [])

    async def candles(self, symbol: str, tf: str, count: int) -> pd.DataFrame:
        msg = await self.call({
            "ticks_history": symbol, "end": "latest", "count": count,
            "style": "candles", "granularity": GRANULARITY[tf], "adjust_start_time": 1,
        })
        if "error" in msg:
            raise RuntimeError(f"{symbol} {tf}: {msg['error'].get('message')}")
        return _to_df(msg.get("candles", []))


# Names people use -> words that appear in Deriv's own market names.
ALIASES = {
    "us tech 100": ["us tech 100", "nasdaq", "ndx", "us tech"],
    "uk 100": ["uk 100", "ftse"],
    "germany 40": ["germany 40", "germany", "dax", "gdaxi"],
    "dxy": ["dxy", "dollar index", "us dollar index"],
    "btcusd": ["btcusd", "bitcoin", "btc/usd"],
    "ethusd": ["ethusd", "ethereum", "eth/usd"],
    "xauusd": ["xauusd", "gold/usd", "gold"],
    "xagusd": ["xagusd", "silver/usd", "silver"],
    "xaueur": ["xaueur", "gold/eur", "gold euro"],
}


def _symbol_fields(entry: dict):
    code = entry.get("underlying_symbol") or entry.get("symbol") or ""
    name = (entry.get("underlying_symbol_name") or entry.get("display_name")
            or entry.get("name") or code)
    return code, name


def resolve(wanted: str, active: list):
    """Match a name like 'Volatility 75 Index' or 'GBP JPY' to a Deriv symbol code."""
    w = _norm(wanted)
    keys = ALIASES.get(wanted.lower().strip(), []) + ALIASES.get(w, []) + [wanted]
    entries = [_symbol_fields(e) for e in active]
    # 1) exact code or exact display-name match
    for code, name in entries:
        if w in (_norm(code), _norm(name)) or _norm(code) in ("frx" + w, "cry" + w):
            return code, name
    # 2) display name contains every key word ("volatility 75 index" -> "Volatility 75 Index")
    for k in keys:
        nk = _norm(k)
        for code, name in entries:
            nn = _norm(name)
            if nk and (nn == nk or nn.startswith(nk) or nk in nn):
                if re.search(r"\d", nk) and not re.search(re.escape(re.sub(r"\D", "", nk)), nn):
                    continue
                return code, name
    return None, None
