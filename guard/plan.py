"""Trade plan for a READY setup: stop, targets, risk-to-reward, lot size."""
import math

from .structure import pivots


def build_plan(direction, conf, poi, h4, spec, account):
    sign = -1 if direction == "sell" else 1          # sells profit when price falls
    entry = conf["entry"]
    buf = max(poi["atr_h4"] * 0.05, spec.get("spread", 0))
    sl = conf["protected"] - sign * buf              # beyond the sweep extreme
    sl_tight = conf["failed_swing"] - sign * buf     # beyond the failure to swing
    t2 = poi.get("draw")                             # last BOS low/high = draw on liquidity
    # T1: internal range liquidity = nearest 4H swing between entry and T2
    hs, ls = pivots(h4, 1)
    pts = [float(h4["low"].iloc[k]) for k in ls] if direction == "sell" else \
          [float(h4["high"].iloc[k]) for k in hs]
    inside = [p for p in pts if t2 is not None and
              (t2 < p < entry if direction == "sell" else entry < p < t2)]
    t1 = (max(inside) if direction == "sell" else min(inside)) if inside else \
         (entry + t2) / 2 if t2 is not None else None

    risk = abs(entry - sl)
    rr = lambda t: round(abs(t - entry) / risk, 2) if t is not None and risk > 0 else None
    plan = {"entry": entry, "stop": sl, "stop_tight": sl_tight, "t1": t1, "t2": t2,
            "rr1": rr(t1), "rr2": rr(t2),
            "invalidation": conf["failed_swing"]}
    best = max([r for r in (plan["rr1"], plan["rr2"]) if r is not None], default=0)
    plan["weak"] = best < 2

    # lot size for the account
    vpp = spec.get("value_per_point")  # money per 1.0 price move per 1.0 lot
    if vpp:
        risk_money = account["balance"] * account["risk_pct"] / 100
        step = spec.get("lot_step", 0.01)
        raw = risk_money / (risk * vpp)
        lot = math.floor(raw / step) * step
        min_lot = spec.get("min_lot", 0.01)
        if lot < min_lot:
            loss = min_lot * risk * vpp
            plan["lot"] = min_lot
            plan["risk_warning"] = (f"Even the smallest lot ({min_lot}) risks "
                                    f"${loss:.2f} = {loss / account['balance'] * 100:.0f}% of your account")
        else:
            plan["lot"] = round(lot, 3)
            plan["risk_money"] = round(lot * risk * vpp, 2)
    return plan
