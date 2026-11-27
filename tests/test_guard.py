import pandas as pd
import pytest

from guard.confirm import confirm
from guard.plan import build_plan
from guard.poi import find_poi, read_trend
from guard.structure import bos_events, mirror

FIX = "tests/fixtures/gold_{}.csv"


def load(tf):
    df = pd.read_csv(FIX.format(tf))
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.iloc[:-1].reset_index(drop=True)


def bars(rows, start="2026-11-27 00:00"):
    t = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame({"time": t, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
                         "low": [r[2] for r in rows], "close": [r[3] for r in rows]})


ZONE = {"top": 110.0, "bottom": 100.0, "atr_h4": 5.0, "draw": 80.0, "bos_level": 85.0}

# a hand-made sell path through every step
SELL_PATH = [
    (88, 89, 87, 88.5), (88.5, 90, 88, 89.5), (89.5, 92, 89, 91.5), (91.5, 95, 91, 94.5),
    (94.5, 98, 94, 97.5), (97.5, 101, 97, 100.5),            # 5: first touch of the zone
    (100.5, 103, 100, 102.5),                                 # 6: swing high 103
    (102.5, 102.6, 101.2, 101.5), (101.5, 101.8, 101.0, 101.2),  # 7-8: dip, low 101.0
    (101.2, 102.0, 101.1, 101.8),
    (101.8, 106.0, 101.6, 102.4),                             # 10: SWEEP above 103, closes back below
    (102.4, 102.5, 100.2, 100.4),                             # 11: takes out 101.0 = validated
    (100.4, 100.6, 99.5, 99.8), (99.8, 101.5, 99.6, 101.2),   # 12 low 99.5
    (101.2, 104.0, 101.0, 103.5),                             # 14: pullback high 104 < 106
    (103.5, 103.6, 102.0, 102.2), (102.2, 102.3, 100.5, 100.8),  # 15-16 confirm lower high
    (100.8, 100.9, 98.0, 98.3),                               # 17: body closes below 99.5 = CISD
    (98.3, 98.5, 97.0, 97.2), (97.2, 97.8, 96.5, 97.5),
]


def test_gold_trend_is_down_on_daily():
    t = read_trend(load("D1"), load("H4"))
    assert t["bias"] == "down" and t["direction"] == "sell" and not t["choppy"]


def test_gold_supply_zone_matches_manual_read():
    p = find_poi("sell", load("D1"), load("H4"))
    assert p["top"] == pytest.approx(3689.63)
    assert p["valid"] and not p["dead"]
    assert p["tapped_before"]                      # touched on 24 Nov
    assert p["draw"] == pytest.approx(3426.46)     # bottom of the BOS leg


def test_wick_only_break_is_not_bos():
    rows = [(10, 11, 9, 10)] * 3 + [(10, 10.5, 7, 9.5), (9.5, 10, 9, 9.8), (9.8, 10, 9.4, 9.9),
                                    (9.9, 10, 9.6, 9.7), (9.7, 9.9, 6.5, 9.6)]  # wick below 7
    assert not [e for e in bos_events(bars(rows)) if e.dir == "down"]


def test_not_reached_zone():
    r = confirm("sell", bars(SELL_PATH[:3]), ZONE)
    assert r["step"] in (2, 3)


def test_sell_path_walks_all_steps():
    seen = {}
    for n in range(6, len(SELL_PATH) + 1):
        seen[n] = confirm("sell", bars(SELL_PATH[:n]), ZONE)["step"]
    assert seen[6] == 4                       # in the zone
    assert seen[11] == 5                      # sweep
    assert seen[12] == 6                      # validated
    r = confirm("sell", bars(SELL_PATH), ZONE)
    assert r["step"] == 9
    assert r["protected"] == 106.0
    assert r["failed_swing"] == 104.0
    assert r["cisd_level"] == 99.5
    assert r["entry_block"]["top"] <= 104.0


def test_entry_hit_and_invalidation():
    hit = SELL_PATH + [(97.5, 100.6, 97.4, 99.0)]
    r = confirm("sell", bars(hit), ZONE)
    assert r["step"] == 10
    broken = SELL_PATH + [(97.5, 104.8, 97.4, 104.5)]  # body closes above failed swing 104
    r = confirm("sell", bars(broken), ZONE)
    assert r["step"] < 9 and any("invalid" in n for n in r["notes"])


def test_buy_is_mirror_of_sell():
    buy_path = [(-o, -l, -h, -c) for o, h, l, c in SELL_PATH]
    zone = {"top": -100.0, "bottom": -110.0, "atr_h4": 5.0, "draw": -80.0, "bos_level": -85.0}
    r = confirm("buy", bars(buy_path), zone)
    assert r["step"] == 9
    assert r["protected"] == -106.0 and r["failed_swing"] == -104.0
    assert r["entry_block"]["bottom"] < r["entry_block"]["top"]


def test_plan_numbers_and_risk_warning():
    r = confirm("sell", bars(SELL_PATH), ZONE)
    h4 = bars([(90, 91, 89, 90), (90, 92, 88, 89), (89, 90, 85, 86), (86, 88, 84, 87), (87, 89, 86, 88)])
    pl = build_plan("sell", r, ZONE, h4, {"value_per_point": 100, "min_lot": 0.01}, {"balance": 100, "risk_pct": 2})
    assert pl["stop"] > 106 and pl["t2"] == 80.0
    assert pl["rr2"] > 2
    assert "risk_warning" in pl                # 0.01 lot on a 7-point stop = $7 > $2


def test_mirror_roundtrip():
    df = bars(SELL_PATH)
    back = mirror(mirror(df))
    assert (back[["open", "high", "low", "close"]].values == df[["open", "high", "low", "close"]].values).all()
