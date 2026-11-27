"""Steps 1-3: trend, last break of structure, and the point of interest (POI).

Everything is written for SELLS (supply zone above price). Buys are handled by
flipping the chart upside down with structure.mirror(), running the same code,
and flipping the answers back.
"""
import pandas as pd

from .structure import (atr, bearish_fvgs, bos_events, last_bullish_candle,
                        mirror, pivots, trend_bias)


def read_trend(d1: pd.DataFrame, h4: pd.DataFrame, n: int = 2) -> dict:
    """Step 1 + 2 on the Daily (falls back to 4H when the Daily has too few breaks)."""
    for tf, df in (("D1", d1), ("H4", h4)):
        ev = bos_events(df, n)
        if len(ev) < 2:
            continue
        bias, against, choppy = trend_bias(ev)
        last_in_trend = next((e for e in reversed(ev) if e.dir == bias), None)
        return {
            "tf": tf,
            "bias": bias,                     # "up" / "down"
            "direction": "buy" if bias == "up" else "sell",
            "choch_against": against,         # 1 = one break against trend (likely trap)
            "choppy": choppy,
            "bos_level": last_in_trend.level if last_in_trend else None,
            "bos_time": str(df["time"].iloc[last_in_trend.i]) if last_in_trend else None,
        }
    return {"tf": None, "bias": None, "direction": None, "choppy": True,
            "choch_against": 0, "bos_level": None, "bos_time": None}


def _refine_with_h1(h1: pd.DataFrame, ob_time, top: float, bottom: float):
    """Refine the 4H order block to the 1H candle that made the high
    (rulebook: POI on 4H, refined down to 1H)."""
    if h1 is None or h1.empty:
        return None
    win = h1[(h1["time"] >= ob_time) &
             (h1["time"] < ob_time + pd.Timedelta(hours=8))].reset_index(drop=True)
    if win.empty:
        return None
    hi = int(win["high"].idxmax())
    j = last_bullish_candle(win, hi, back=4)
    r_bottom = float(win["low"].iloc[j])
    r_top = max(float(win["high"].iloc[j]), float(win["high"].iloc[hi]))
    tol = (top - bottom) * 0.05
    if not (bottom - tol <= r_bottom < r_top <= top + tol):
        return None
    return r_bottom, r_top, win["time"].iloc[j]


def _sell_poi(d1, h4, h1, n=2):
    ev = [e for e in bos_events(h4, n) if e.dir == "down"]
    if not ev:
        return None
    e = ev[-1]
    H, L, C = h4["high"].to_numpy(), h4["low"].to_numpy(), h4["close"].to_numpy()
    seg = h4.iloc[e.swing_idx:e.i + 1]
    leg_hi = int(seg["high"].idxmax())
    ob = last_bullish_candle(h4, leg_hi)
    # refine to the next candle if it swept the OB candle and left a gap
    if ob + 2 < len(h4) and H[ob + 1] > H[ob] and L[ob] > H[ob + 2]:
        ob = ob + 1
    top, bottom = float(max(H[ob], H[leg_hi])), float(L[ob])
    ob_time = h4["time"].iloc[ob]
    refined = _refine_with_h1(h1, ob_time, top, bottom)
    if refined:
        bottom, top, ob_time = refined[0], max(refined[1], float(H[leg_hi])), refined[2]

    # --- the 5 order block checks ---
    checks = {}
    checks["broke_structure"] = True  # by construction: its leg made the last bearish BOS
    prev = max(ob - 1, 0)
    checks["swept_prev_wick"] = bool(max(H[ob], H[leg_hi]) > H[prev])
    checks["left_fvg"] = bool(bearish_fvgs(h4, ob, e.i + 1))
    # HTF key level in line with the trend: zone sits in the premium (upper half)
    # of the daily range made since the last daily swing high at/above the zone
    d_hi, _ = pivots(d1, 2)
    cand = [k for k in d_hi if d1["high"].iloc[k] >= bottom]
    if cand:
        k = cand[-1]
        rng_hi, rng_lo = float(d1["high"].iloc[k]), float(d1["low"].iloc[k:].min())
    else:
        rng_hi, rng_lo = float(d1["high"].tail(30).max()), float(d1["low"].tail(30).min())
    checks["htf_premium"] = bool((top + bottom) / 2 > (rng_hi + rng_lo) / 2)
    # liquidity in front: a swing high (or equal highs) below the zone, formed after it
    sh, _ = pivots(h4, 1)
    checks["liquidity_in_front"] = bool([k for k in sh if k > leg_hi + 1 and H[k] < bottom])

    # zone health
    a = atr(h4)
    dead = bool((C[leg_hi + 1:] > top).any())
    far = [i for i in range(leg_hi + 1, len(h4)) if H[i] < bottom - a]
    tapped_before = bool(far) and bool((H[leg_hi + 2:far[-1] + 1] >= bottom).any())
    draw = float(L[leg_hi:].min())  # where the BOS leg reached = draw on liquidity
    return {
        "top": top, "bottom": bottom, "ob_time": str(ob_time),
        "bos_level": e.level, "draw": draw, "checks": checks,
        "valid": all(checks.values()), "dead": dead,
        "tapped_before": tapped_before, "atr_h4": a,
    }


def find_poi(direction, d1, h4, h1=None, n=2):
    if direction == "sell":
        return _sell_poi(d1, h4, h1, n)
    p = _sell_poi(mirror(d1), mirror(h4), mirror(h1) if h1 is not None else None, n)
    if not p:
        return None
    p["top"], p["bottom"] = -p["bottom"], -p["top"]
    p["bos_level"], p["draw"] = -p["bos_level"], -p["draw"]
    return p


def check_manual_zone(direction, zone, h4):
    """A zone you set yourself: skip the auto checks, still watch for invalidation."""
    df = h4 if direction == "sell" else mirror(h4)
    top, bottom = (zone["top"], zone["bottom"]) if direction == "sell" else (-zone["bottom"], -zone["top"])
    a = atr(df)
    return {"top": zone["top"], "bottom": zone["bottom"], "ob_time": "manual",
            "bos_level": zone.get("bos_level"), "draw": zone.get("target"),
            "checks": {"manual_zone": True}, "valid": True,
            "dead": bool(df["close"].iloc[-6:].gt(top).any()),
            "tapped_before": False, "atr_h4": a}
