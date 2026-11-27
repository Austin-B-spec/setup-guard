"""Candlestick picture of a setup for the Telegram alert."""
import matplotlib

matplotlib.use("Agg")
import mplfinance as mpf  # noqa: E402


def draw(m15, name, poi, conf, plan, path):
    df = m15.tail(120).set_index("time")[["open", "high", "low", "close"]]
    df.index = df.index.tz_convert(None)
    lines, colors = [], []
    for key, col in (("entry", "#1f77b4"), ("stop", "#d62728"), ("t1", "#2ca02c"), ("t2", "#2ca02c")):
        if plan and plan.get(key) is not None:
            lines.append(plan[key]); colors.append(col)
    fill = dict(y1=poi["bottom"], y2=poi["top"], alpha=0.15, color="orange")
    kw = dict(type="candle", style="charles", title=f"{name} 15m  (orange=POI  blue=entry  red=SL  green=targets)",
              fill_between=fill, savefig=dict(fname=path, dpi=110), figsize=(10, 6))
    if lines:
        kw["hlines"] = dict(hlines=lines, colors=colors, linestyle="--", linewidths=1)
    mpf.plot(df, **kw)
    return path
