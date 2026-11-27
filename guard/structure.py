"""Market structure helpers: swing points, breaks of structure, trend bias.

All functions work on a pandas DataFrame with columns open, high, low, close
(index 0..N-1, oldest first) and only closed candles.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Bos:
    i: int            # bar whose body closed beyond the level
    dir: str          # "up" or "down"
    level: float      # swing price that was broken
    swing_idx: int    # bar of the swing that was broken


def mirror(df: pd.DataFrame) -> pd.DataFrame:
    """Flip prices upside down so a buy setup can be read with sell logic."""
    out = df.copy()
    out["open"], out["close"] = -df["open"], -df["close"]
    out["high"], out["low"] = -df["low"], -df["high"]
    return out


def pivots(df: pd.DataFrame, n: int = 2):
    """Swing highs/lows: a bar higher (lower) than the n bars on each side."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    highs, lows = [], []
    for i in range(n, len(df) - n):
        left_h, right_h = h[i - n:i], h[i + 1:i + n + 1]
        if h[i] > left_h.max() and h[i] >= right_h.max():
            highs.append(i)
        left_l, right_l = l[i - n:i], l[i + 1:i + n + 1]
        if l[i] < left_l.min() and l[i] <= right_l.min():
            lows.append(i)
    return highs, lows


def bos_events(df: pd.DataFrame, n: int = 2):
    """Every break of structure, counted only when a candle BODY closes beyond
    a confirmed swing. Wick-only breaks are ignored (they are inducement)."""
    highs, lows = pivots(df, n)
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    events, act_h, act_l = [], [], []
    hp = lp = 0
    for i in range(len(df)):
        while hp < len(highs) and highs[hp] + n < i:
            act_h.append(highs[hp]); hp += 1
        while lp < len(lows) and lows[lp] + n < i:
            act_l.append(lows[lp]); lp += 1
        up = [k for k in act_h if c[i] > h[k]]
        if up:
            k = max(up)
            events.append(Bos(i, "up", float(h[k]), k))
            act_h = [x for x in act_h if x not in up]
        down = [k for k in act_l if c[i] < l[k]]
        if down:
            k = max(down)
            events.append(Bos(i, "down", float(l[k]), k))
            act_l = [x for x in act_l if x not in down]
    return events


def trend_bias(events):
    """Direction of the trend. One break against the trend (a CHoCH) is treated
    as a likely trap: the bias only flips after two breaks in a row the other way.
    Returns (bias, pending_choch_count, choppy)."""
    bias, against = None, 0
    for e in events:
        if bias is None:
            bias = e.dir
        elif e.dir == bias:
            against = 0
        else:
            against += 1
            if against >= 2:
                bias, against = e.dir, 0
    last = [e.dir for e in events[-6:]]
    flips = sum(1 for a, b in zip(last, last[1:]) if a != b)
    choppy = len(last) >= 5 and flips >= 4
    return bias, against, choppy


def atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.tail(n).mean())


def bearish_fvgs(df: pd.DataFrame, start: int, end: int):
    """Fair value gaps left by a drop: candle q-1's low sits above candle q+1's high.
    Returns list of (q, gap_bottom, gap_top)."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    out = []
    for q in range(max(start, 1), min(end, len(df) - 2) + 1):
        if l[q - 1] > h[q + 1]:
            out.append((q, float(h[q + 1]), float(l[q - 1])))
    return out


def last_bullish_candle(df: pd.DataFrame, at: int, back: int = 6) -> int:
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    for j in range(at, max(at - back, -1), -1):
        if c[j] > o[j]:
            return j
    return at


__all__ = ["Bos", "mirror", "pivots", "bos_events", "trend_bias", "atr",
           "bearish_fvgs", "last_bullish_candle", "np"]
