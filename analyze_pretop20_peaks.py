#!/usr/bin/env python3
"""Analyze pretop20 screener snapshots: what early premarket behavior predicts
the biggest price peakers of the day, and how much upside is left after the
signal fires.

Data: pretop20/screener_YYYYMMDD_HHMMSS.json, one snapshot/minute, fields per
ticker: premarket_change (live % vs prev close), premarket_volume (cumulative),
close (previous close, static).
"""

import glob
import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretop20")


def load_all():
    rows = []
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "screener_*.json"))):
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        ts = pd.Timestamp(d["timestamp"])
        total_vol = sum(r.get("premarket_volume") or 0 for r in d["data"])
        for r in d["data"]:
            rows.append(
                {
                    "date": ts.date(),
                    "ts": ts,
                    "ticker": r["name"],
                    "pm_change": r.get("premarket_change"),
                    "pm_vol": r.get("premarket_volume") or 0,
                    "close": r.get("close"),
                    "vol_share": (r.get("premarket_volume") or 0) / total_vol if total_vol else 0,
                }
            )
    df = pd.DataFrame(rows).dropna(subset=["pm_change"])
    return df


def build_series(df):
    """dict[(date,ticker)] -> per-ticker dataframe sorted by time."""
    out = {}
    for key, g in df.groupby(["date", "ticker"]):
        g = g.sort_values("ts").reset_index(drop=True)
        # drop frozen tickers (stale quotes: pm_change never moves)
        if len(g) < 10 or g["pm_change"].nunique() < 3:
            continue
        out[key] = g
    return out


def day_winners(series):
    print("=" * 78)
    print("DAY WINNERS: ticker with highest peak premarket_change each day")
    print("=" * 78)
    recs = []
    for (date, tic), g in series.items():
        recs.append(
            {
                "date": date,
                "ticker": tic,
                "first_seen": g["ts"].iloc[0].strftime("%H:%M"),
                "first_chg": g["pm_change"].iloc[0],
                "peak_chg": g["pm_change"].max(),
                "peak_time": g.loc[g["pm_change"].idxmax(), "ts"].strftime("%H:%M"),
                "last_chg": g["pm_change"].iloc[-1],
                "peak_vol_share": g["vol_share"].max(),
                "prev_close": g["close"].iloc[0],
            }
        )
    R = pd.DataFrame(recs)
    win = R.loc[R.groupby("date")["peak_chg"].idxmax()]
    with pd.option_context("display.width", 200):
        print(
            win[
                ["date", "ticker", "first_seen", "first_chg", "peak_chg", "peak_time", "last_chg", "prev_close"]
            ].to_string(index=False, float_format=lambda x: f"{x:.1f}")
        )
    # retention: how much of the peak is kept at 9:29
    win = win.copy()
    win["keep_ratio"] = (1 + win["last_chg"] / 100) / (1 + win["peak_chg"] / 100)
    print(f"\nWinners' price at open vs at peak (1.0 = no fade): "
          f"median {win['keep_ratio'].median():.2f}, range {win['keep_ratio'].min():.2f}-{win['keep_ratio'].max():.2f}")
    return R


def peak_time_distribution(R):
    print("\n" + "=" * 78)
    print("WHEN DO BIG MOVERS PEAK? (all ticker-days with peak >= 30%)")
    print("=" * 78)
    big = R[R["peak_chg"] >= 30].copy()
    big["peak_hour"] = big["peak_time"].str[:2].astype(int)
    dist = big["peak_hour"].value_counts().sort_index()
    for h, n in dist.items():
        et = h - 12  # local 16:00 == 4:00 ET
        print(f"  {h:02d}:00-{h:02d}:59 local ({et}:00 ET)  {'#' * n} {n}")
    print(f"  n = {len(big)} ticker-days")


def make_events(series, window=15, min_chg=5.0):
    """For each ticker-day: features over first `window` snapshots after first
    appearance (>= min_chg at entry), outcome = what happens afterwards."""
    events = []
    for (date, tic), g in series.items():
        if len(g) < window + 10:
            continue
        if g["pm_change"].iloc[0] < min_chg:
            # start the clock when it first crosses min_chg instead
            idx = g.index[g["pm_change"] >= min_chg]
            if len(idx) == 0 or idx[0] + window + 10 > len(g):
                continue
            g = g.loc[idx[0]:].reset_index(drop=True)
        w = g.iloc[:window]
        fut = g.iloc[window:]

        price = 1 + w["pm_change"].values / 100
        dprice = np.diff(price)
        dvol = np.diff(w["pm_vol"].values)
        minutes = (w["ts"].iloc[-1] - w["ts"].iloc[0]).total_seconds() / 60 or 1

        ev = {
            "date": date,
            "ticker": tic,
            "entry_time": w["ts"].iloc[0].strftime("%H:%M"),
            "chg_at_entry": w["pm_change"].iloc[0],
            "chg_at_signal": w["pm_change"].iloc[-1],
            "prev_close": w["close"].iloc[0],
            # features
            "win_gain": price[-1] / price[0] - 1,                      # gain during window
            "up_ratio": (dprice > 0).mean(),                           # fraction of up minutes
            "max_up_streak": _max_streak(dprice > 0),
            "vol_rate": dvol.sum() / minutes,                          # shares/min in window
            "vol_dollar_rate": dvol.sum() / minutes * w["close"].iloc[0] * price[-1],
            "vol_accel": _safe_ratio(dvol[len(dvol) // 2:].sum(), dvol[: len(dvol) // 2].sum()),
            "pv_corr": _safe_corr(dprice, dvol[: len(dprice)]),
            "vol_share": w["vol_share"].iloc[-1],
            "vol_share_trend": w["vol_share"].iloc[-1] - w["vol_share"].iloc[0],
        }
        # outcome: best gain available AFTER the signal, from signal price
        sig_price = price[-1]
        fut_price = 1 + fut["pm_change"].values / 100
        ev["future_max_gain"] = fut_price.max() / sig_price - 1
        ev["future_end_gain"] = fut_price[-1] / sig_price - 1
        peak_i = fut_price.argmax()
        ev["mins_to_peak"] = (fut["ts"].iloc[peak_i] - w["ts"].iloc[-1]).total_seconds() / 60
        events.append(ev)
    return pd.DataFrame(events)


def _max_streak(b):
    best = cur = 0
    for x in b:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def _safe_ratio(a, b):
    return a / b if b > 0 else np.nan


def _safe_corr(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def feature_analysis(E):
    print("\n" + "=" * 78)
    print(f"PREDICTIVE FEATURES (n={len(E)} events: ticker first seen with >=5% gain,")
    print("features measured over first 15 minutes, outcome = max gain afterwards)")
    print("=" * 78)
    E = E.copy()
    E["success"] = E["future_max_gain"] >= 0.20

    feats = [
        ("win_gain", "Gain during first 15 min"),
        ("up_ratio", "Fraction of minutes price rose"),
        ("max_up_streak", "Longest consecutive-up streak"),
        ("vol_rate", "Volume per minute (shares)"),
        ("vol_dollar_rate", "Dollar volume per minute"),
        ("vol_accel", "Volume accel (2nd half / 1st half)"),
        ("pv_corr", "Price-move/volume correlation"),
        ("vol_share", "Share of total screener volume"),
        ("vol_share_trend", "Volume share rising?"),
        ("chg_at_signal", "Gain level at signal time"),
        ("prev_close", "Previous close price"),
    ]
    print(f"\nBase rate: {E['success'].mean():.0%} of events gain another 20%+ after the signal; "
          f"median future max gain {E['future_max_gain'].median():+.1%}\n")
    print(f"{'feature':<34}{'spearman':>9}   success rate by quartile (Q1->Q4)")
    print("-" * 78)
    for col, label in feats:
        e = E.dropna(subset=[col])
        rho = e[col].rank().corr(e["future_max_gain"].rank())
        try:
            q = pd.qcut(e[col], 4, duplicates="drop")
            sr = e.groupby(q, observed=True)["success"].mean()
            srs = "  ".join(f"{v:.0%}" for v in sr)
            mg = e.groupby(q, observed=True)["future_max_gain"].median()
            mgs = "  ".join(f"{v:+.0%}" for v in mg)
        except ValueError:
            srs = mgs = "n/a"
        print(f"{label:<34}{rho:>+8.2f}   {srs}")
        print(f"{'':<34}{'':>9}   med future gain: {mgs}")
    return E


def combo_rules(E):
    print("\n" + "=" * 78)
    print("COMBINED ENTRY RULES (evaluated at minute 15 after first appearance)")
    print("=" * 78)
    E = E.copy()
    rules = {
        "ALL events (baseline)": pd.Series(True, index=E.index),
        "Price still rising (win_gain>0)": E["win_gain"] > 0,
        "win_gain > 10%": E["win_gain"] > 0.10,
        "up_ratio >= 0.5": E["up_ratio"] >= 0.5,
        "vol_accel > 1 (volume speeding up)": E["vol_accel"] > 1,
        "rising price + accelerating volume": (E["win_gain"] > 0) & (E["vol_accel"] > 1),
        "rising + accel vol + up_ratio>=0.5": (E["win_gain"] > 0) & (E["vol_accel"] > 1) & (E["up_ratio"] >= 0.5),
        "rising + accel vol + $vol>$50k/min": (E["win_gain"] > 0) & (E["vol_accel"] > 1) & (E["vol_dollar_rate"] > 50_000),
        "FADING already (win_gain < -5%)": E["win_gain"] < -0.05,
    }
    print(f"{'rule':<42}{'n':>5}{'win20%':>8}{'medMax':>8}{'medEnd':>8}{'medMin2Pk':>10}")
    print("-" * 82)
    for name, mask in rules.items():
        e = E[mask.fillna(False)]
        if len(e) == 0:
            continue
        print(
            f"{name:<42}{len(e):>5}{e['future_max_gain'].ge(0.2).mean():>8.0%}"
            f"{e['future_max_gain'].median():>+8.1%}{e['future_end_gain'].median():>+8.1%}"
            f"{e['mins_to_peak'].median():>10.0f}"
        )
    print("\nwin20% = % of events gaining 20%+ more after signal; medMax = median best")
    print("gain after signal; medEnd = median gain if held to 9:29; medMin2Pk = median")
    print("minutes from signal to the post-signal peak.")


def winner_early_signature(E, R):
    print("\n" + "=" * 78)
    print("DID THE DAY'S #1 PEAKER LOOK DIFFERENT IN ITS FIRST 15 MINUTES?")
    print("=" * 78)
    win_keys = set(
        R.loc[R.groupby("date")["peak_chg"].idxmax()][["date", "ticker"]].itertuples(index=False, name=None)
    )
    E = E.copy()
    E["is_winner"] = E.apply(lambda r: (r["date"], r["ticker"]) in win_keys, axis=1)
    cols = ["win_gain", "up_ratio", "vol_accel", "vol_share", "vol_dollar_rate", "chg_at_signal", "prev_close"]
    cmp = E.groupby("is_winner")[cols].median().T
    cmp.columns = ["others (median)", "day winner (median)"]
    print(cmp.to_string(float_format=lambda x: f"{x:,.3f}"))


def main():
    df = load_all()
    print(f"Loaded {df['ts'].nunique()} snapshots, {len(df)} rows, "
          f"{df['date'].nunique()} days, {df['ticker'].nunique()} unique tickers")
    series = build_series(df)
    R = day_winners(series)
    peak_time_distribution(R)
    E = make_events(series)
    E = feature_analysis(E)
    combo_rules(E)
    winner_early_signature(E, R)


if __name__ == "__main__":
    main()
