"""Steps 4-9 on the 15-minute chart.

4 mitigation        price returns into the POI
5 liquidity sweep   a wick takes a 15m swing high, candle closes back below it
6 sweep validated   price then takes out the low that fed the sweep
7 failure to swing  pullback makes a lower high (fails to beat the sweep extreme)
8 CISD              a body closes below the low the failed swing started from
9 entry block       the FVG (or order block) left by the CISD leg

Written for sells; buys are run on a mirrored chart.
"""
import pandas as pd

from .structure import bearish_fvgs, last_bullish_candle, mirror, pivots

STEP_NAMES = {
    3: "Approaching POI",
    4: "In POI - waiting for 15m liquidity sweep",
    5: "Sweep done - waiting for validation (break of the low that fed it)",
    6: "Sweep validated - waiting for failure to swing",
    7: "Failure to swing - waiting for change in state of delivery",
    8: "CISD done - waiting for entry block",
    9: "READY - entry block formed",
    10: "Price is in the entry block now",
}


def _t(df, i):
    return str(df["time"].iloc[i]) if i is not None and 0 <= i < len(df) else None


def _sell_confirm(m: pd.DataFrame, zone_top: float, zone_bottom: float, atr_h4: float,
                  n: int = 2, lookback: int = 96) -> dict:
    H, L, C = m["high"].to_numpy(), m["low"].to_numpy(), m["close"].to_numpy()
    N = len(m)
    out = {"step": 0, "notes": []}
    if N < 3:
        out["notes"].append("not enough 15m candles")
        return out

    # Step 4: find the start of the current visit to the zone
    far_level = zone_bottom - atr_h4
    far = [i for i in range(N) if H[i] < far_level]
    first = far[-1] + 1 if far else 0
    touches = [i for i in range(first, N) if H[i] >= zone_bottom]
    if not touches:
        dist = zone_bottom - C[-1]
        out.update(step=3 if dist <= atr_h4 else 2, distance=float(dist))
        return out
    t0 = touches[0]
    out.update(step=4, t0=_t(m, t0))

    highs, _ = pivots(m, n)
    tol = (zone_top - zone_bottom) * 0.25
    start = t0
    for _round in range(20):  # each round = one attempt at steps 5-9
        # ---- Step 5: liquidity sweep (any CHoCH/BOS before it is ignored as a trap)
        sweep = None
        for j in range(start, N):
            if H[j] < zone_bottom - tol:
                continue
            for k in reversed(highs):
                if k + n >= j:
                    continue
                if k < t0 - lookback:
                    break
                if k + 1 < j and H[k + 1:j].max() > H[k]:
                    continue  # that high was already taken
                if H[j] > H[k] and C[j] < H[k]:
                    sweep = (j, k)
                    break
            if sweep:
                break
        if not sweep:
            return out
        j, k = sweep
        V = float(L[k + 1:j + 1].min())  # the low price rallied from into the sweep
        P = float(H[j])
        out.update(step=5, sweep_time=_t(m, j), swept_level=float(H[k]),
                   protected=P, validation_level=V)

        # ---- Step 6: price takes out the low that fed the sweep
        v = None
        for x in range(j + 1, N):
            if H[x] > P:
                P = float(H[x])
            if L[x] < V:
                v = x
                break
        out["protected"] = P
        if v is None:
            return out
        out.update(step=6, validated_time=_t(m, v))

        # ---- Step 7 + 8: failure to swing, then CISD
        restart = None
        for x in range(v + 1, N):
            if H[x] > P:
                restart = x
                break
        cands = [y for y in highs if v < y and y + n < N and H[y] < P
                 and (restart is None or y < restart)]
        done = False
        for y in cands:
            L2 = float(L[v:y].min()) if y > v else float(L[v])
            out.update(step=7, failed_swing=float(H[y]), failed_swing_time=_t(m, y),
                       cisd_level=L2)
            z = None
            for x in range(y + 1, N):
                if H[x] > H[y]:
                    break  # pullback went higher - try the next swing
                if C[x] < L2:
                    z = x
                    break
            if z is None:
                continue
            out.update(step=8, cisd_time=_t(m, z))
            # ---- Step 9: entry block from the CISD leg
            fvgs = bearish_fvgs(m, y, z)
            if fvgs:
                q, b, t = min(fvgs, key=lambda g: g[1])  # nearest gap above price
                block = {"type": "FVG", "bottom": b, "top": t, "time": _t(m, q)}
                formed = q + 1
            else:
                ob = last_bullish_candle(m, y, back=4)
                block = {"type": "order block", "bottom": float(L[ob]),
                         "top": float(max(H[ob], H[y])), "time": _t(m, ob)}
                formed = z
            out.update(step=9, entry_block=block, entry=(block["bottom"] + block["top"]) / 2)
            after = range(max(z, formed) + 1, N)
            if any(C[x] > H[y] for x in after):
                out["notes"].append("body closed above the failed swing after CISD - setup invalid")
                restart = next(x for x in after if C[x] > H[y])
                break
            if any(H[x] >= block["bottom"] for x in after):
                out["step"] = 10
            done = True
            break
        if done:
            return out
        if restart is None:
            return out
        out["notes"].append(f"setup reset at {_t(m, restart)} - looking for a new sweep")
        notes = out["notes"]
        out = {"step": 4, "t0": _t(m, t0), "notes": notes}
        start = restart
    return out


def confirm(direction: str, m15: pd.DataFrame, poi: dict, n: int = 2) -> dict:
    if direction == "sell":
        return _sell_confirm(m15, poi["top"], poi["bottom"], poi["atr_h4"], n)
    r = _sell_confirm(mirror(m15), -poi["bottom"], -poi["top"], poi["atr_h4"], n)
    for key in ("swept_level", "protected", "validation_level", "failed_swing",
                "cisd_level", "entry", "distance"):
        if key in r and key != "distance":
            r[key] = -r[key]
    if "entry_block" in r:
        b = r["entry_block"]
        b["bottom"], b["top"] = -b["top"], -b["bottom"]
    return r
