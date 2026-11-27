"""Setup Guard: runs every few minutes on GitHub, checks every market against the
Varis checklist and messages you when something moves to a new step.

    python -m guard.main            normal run
    python -m guard.main --test     send a test report of every market now
"""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import pandas as pd
import yaml

from . import notify
from .confirm import STEP_NAMES, confirm
from .data import Feed, resolve
from .plan import build_plan
from .poi import check_manual_zone, find_poi, read_trend

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "state.json")
COUNTS = {"D1": 150, "H4": 300, "H1": 400, "M15": 400}
DISCLAIMER = "Analysis only, not financial advice. Confirm on your chart; lot size and risk are your call."


def fmt(x, ref=None):
    if x is None:
        return "-"
    d = 5 if abs(ref or x) < 20 else 3 if abs(ref or x) < 1000 else 2
    return f"{x:.{d}f}"


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"sent": [], "tg_offset": 0, "unresolved_reported": False}


def save_state(state):
    state["sent"] = state["sent"][-800:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)


def closed(df):
    """Drop the candle that is still forming."""
    return df.iloc[:-1].reset_index(drop=True) if len(df) > 1 else df


def verdict(step, valid=True):
    if not valid:
        return "SKIP"
    return {9: "READY", 10: "READY - IN ENTRY"}.get(step, "NEARLY READY" if step in (7, 8) else "WAIT")


async def scan_market(feed, code, name, cfg):
    data = {tf: await feed.candles(code, tf, n) for tf, n in COUNTS.items()}
    m15_all = data["M15"]
    if m15_all.empty:
        return [{"name": name, "status": "no data"}]
    age = datetime.now(timezone.utc) - m15_all["time"].iloc[-1]
    if age > pd.Timedelta(hours=3):
        return [{"name": name, "status": "market closed"}]
    d1, h4, h1, m15 = (closed(data[t]) for t in ("D1", "H4", "H1", "M15"))
    price = float(m15_all["close"].iloc[-1])

    trend = read_trend(d1, h4)
    results = []
    zones = []
    if trend["bias"] and not trend["choppy"]:
        p = find_poi(trend["direction"], d1, h4, h1)
        if p:
            p["source"] = "auto"
            zones.append((trend["direction"], p))
    for z in (cfg.get("manual_zones") or {}).get(name, []):
        mz = check_manual_zone(z["direction"], z, h4)
        auto = find_poi(z["direction"], d1, h4, h1)
        if auto:  # borrow targets from the auto read when you didn't set them
            mz["draw"] = mz["draw"] if mz["draw"] is not None else auto["draw"]
            mz["bos_level"] = mz["bos_level"] or auto["bos_level"]
        mz["source"] = "manual"
        # drop the auto zone if it is basically the same box
        zones = [(d, q) for d, q in zones if not (d == z["direction"] and
                 min(q["top"], mz["top"]) - max(q["bottom"], mz["bottom"]) >
                 0.5 * (mz["top"] - mz["bottom"]))]
        zones.append((z["direction"], mz))

    if not zones:
        reason = "consolidating / choppy" if trend["choppy"] else "no trend or no valid POI"
        return [{"name": name, "status": "SKIP", "reason": reason, "trend": trend, "price": price}]

    for direction, poi in zones:
        conf = confirm(direction, m15, poi) if not poi["dead"] else {"step": 0, "notes": []}
        r = {"name": name, "code": code, "direction": direction, "trend": trend, "poi": poi,
             "conf": conf, "price": price, "m15": m15_all}
        failed = [k for k, ok in poi["checks"].items() if not ok]
        r["valid"] = poi["valid"] and not poi["dead"]
        r["status"] = "SKIP" if not r["valid"] else verdict(conf["step"])
        if poi["dead"]:
            r["reason"] = "zone broken (4H body closed through it)"
        elif failed:
            r["reason"] = "POI fails: " + ", ".join(failed)
        if conf["step"] >= 9:
            spec = (cfg.get("contract_specs") or {}).get(name, {})
            r["plan"] = build_plan(direction, conf, poi, h4, spec, cfg["account"])
        results.append(r)
    return results


def zone_key(r):
    p = r["poi"]
    return f"{r['name']}|{r['direction']}|{p['top']:.5f}|{p['bottom']:.5f}"


def alert_for(r):
    step = r["conf"]["step"]
    return {3: "approaching", 4: "in_zone", 5: "sweep", 6: "sweep", 7: "sweep",
            8: "cisd", 9: "ready", 10: "entry_hit"}.get(step)


def message(r, kind):
    p, c, t = r["poi"], r["conf"], r["trend"]
    side = r["direction"].upper()
    ref = r["price"]
    head = {"approaching": "👀", "in_zone": "🟡", "sweep": "🟠", "cisd": "🟠",
            "ready": "🟢", "entry_hit": "🔵", "invalidated": "🔴"}[kind]
    lines = [f"{head} {r['name']} {side} - {STEP_NAMES.get(c['step'], kind)} (step {min(c['step'], 9)}/9)",
             f"Trend: {t['bias'] or '?'} ({t['tf']}) | POI {fmt(p['bottom'], ref)}-{fmt(p['top'], ref)} ({p['source']})",
             f"Price now: {fmt(ref)}"]
    if p.get("tapped_before"):
        lines.append("⚠️ zone was already tapped once - weaker")
    if t.get("choch_against"):
        lines.append("⚠️ one break against the trend on the HTF - could be a trap or a turn")
    if c.get("swept_level") is not None:
        lines.append(f"Sweep of {fmt(c['swept_level'], ref)} | protected {fmt(c['protected'], ref)}")
    if c.get("failed_swing") is not None:
        lines.append(f"Failed swing {fmt(c['failed_swing'], ref)} | CISD level {fmt(c['cisd_level'], ref)}")
    pl = r.get("plan")
    if pl and kind in ("ready", "entry_hit"):
        b = c["entry_block"]
        lines += [f"Entry {fmt(pl['entry'], ref)} ({b['type']} {fmt(b['bottom'], ref)}-{fmt(b['top'], ref)})",
                  f"SL {fmt(pl['stop'], ref)} | tight SL {fmt(pl['stop_tight'], ref)}",
                  f"T1 {fmt(pl['t1'], ref)} (RR {pl['rr1']}) | T2 {fmt(pl['t2'], ref)} (RR {pl['rr2']})",
                  f"Invalid if a 15m body closes beyond {fmt(pl['invalidation'], ref)}"]
        if pl.get("weak"):
            lines.append("⚠️ Risk-to-reward under 1:2 - weak setup, rulebook says skip")
        if pl.get("risk_warning"):
            lines.append("⚠️ " + pl["risk_warning"])
        elif pl.get("lot"):
            lines.append(f"Lot {pl['lot']} ≈ ${pl['risk_money']} risk")
    if kind == "invalidated":
        lines.append(r.get("reason") or "setup broken")
    lines.append(DISCLAIMER)
    full = "\n".join(lines)
    short = "\n".join(lines[:3] + ([lines[-2]] if pl else []))
    return full, short


def summary(results, unresolved):
    order = {"READY - IN ENTRY": 0, "READY": 1, "NEARLY READY": 2, "WAIT": 3, "SKIP": 4}
    rows = sorted([r for r in results if "conf" in r],
                  key=lambda r: (order.get(r["status"], 5), -r["conf"]["step"]))
    out = [f"📊 Setup Guard status {datetime.now(timezone.utc):%d %b %H:%M} UTC"]
    for r in rows[:40]:
        step = r["conf"]["step"]
        out.append(f"{r['status']}: {r['name']} {r['direction']} step {min(step, 9)} "
                   f"POI {fmt(r['poi']['bottom'], r['price'])}-{fmt(r['poi']['top'], r['price'])}"
                   + (f" ({r['reason']})" if r.get("reason") and r["status"] == "SKIP" else ""))
    others = [r for r in results if "conf" not in r]
    if others:
        out.append("Other: " + "; ".join(f"{r['name']} {r['status']}" +
                                        (f" ({r['reason']})" if r.get('reason') else "")
                                        for r in others))
    if unresolved:
        out.append("Not on the free Deriv feed: " + ", ".join(unresolved))
    out.append(DISCLAIMER)
    return "\n".join(out)


async def run(test=False):
    with open(os.path.join(ROOT, "config.yml")) as f:
        cfg = yaml.safe_load(f)
    state = load_state()
    sent_list = list(state["sent"])
    sent = set(sent_list)
    cmds, state["tg_offset"] = notify.telegram_commands(state.get("tg_offset", 0))
    want_status = test or any(c in ("status", "/status", "check", "scan") for c in cmds)

    results, unresolved = [], []
    async with Feed() as feed:
        active = await feed.symbols()
        for wanted in cfg["markets"]:
            code, _ = resolve(wanted, active)
            if not code:
                unresolved.append(wanted)
                continue
            try:
                results += await scan_market(feed, code, wanted, cfg)
            except Exception as e:  # one bad market must not stop the rest
                results.append({"name": wanted, "status": "error", "reason": str(e)[:120]})

    if unresolved and not state.get("unresolved_reported"):
        notify.send("ℹ️ These markets are not on the free Deriv feed, so they are not watched: "
                    + ", ".join(unresolved))
        state["unresolved_reported"] = True

    for r in results:
        if "conf" not in r:
            continue
        key = zone_key(r)
        if r["poi"]["dead"] or not r["valid"]:
            if any(s.startswith(key + "|") for s in sent) and f"{key}|invalidated" not in sent \
                    and cfg["alerts"].get("invalidated") and r["poi"]["dead"]:
                full, short = message(r, "invalidated")
                notify.send(full, short)
                sent.add(f"{key}|invalidated"); sent_list.append(f"{key}|invalidated")
            continue
        kind = alert_for(r)
        visit = r["conf"].get("t0", "")
        tag = f"{key}|{kind}|{visit}"
        if not kind or tag in sent or not cfg["alerts"].get(kind):
            continue
        photo = None
        if kind in ("ready", "entry_hit"):
            try:
                from .chart import draw
                photo = draw(r["m15"], r["name"], r["poi"], r["conf"], r.get("plan"),
                             os.path.join(tempfile.gettempdir(), f"{r['code']}.png"))
            except Exception as e:
                print("chart error:", e)
        full, short = message(r, kind)
        notify.send(full, short, photo)
        sent.add(tag); sent_list.append(tag)

    if want_status:
        text = summary(results, unresolved)
        notify.telegram(text)
        print(text)

    state["sent"] = sent_list
    save_state(state)


def main():
    asyncio.run(run(test="--test" in sys.argv))


if __name__ == "__main__":
    main()
