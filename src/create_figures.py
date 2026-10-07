#!/usr/bin/env python3
"""Create static portfolio figures from verified output tables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


RUN = ROOT / "outputs" / "run_20260915"
TABLES = RUN / "tables"
FIGURES = RUN / "figures"


def save(name: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURES / name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="talk")
    blue, amber = "#2563EB", "#D97706"

    monthly = pd.read_csv(TABLES / "monthly_kpis.csv")
    complete = monthly.loc[monthly["is_complete_month"]].copy()
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(complete["month"], complete["net_revenue"] / 1_000_000, color=blue, marker="o", linewidth=2.5)
    ax.set(title="Monthly net revenue (complete months)", xlabel="Month", ylabel="Net revenue (million)")
    ax.tick_params(axis="x", rotation=55, labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    save("01_monthly_net_revenue.png")

    cohort = pd.read_csv(TABLES / "cohort_repeat.csv")
    mature = cohort.loc[cohort["mature_90d"]].copy()
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(mature["cohort_month"], mature["repeat_90d_rate"] * 100, color=amber, marker="o", linewidth=2.5)
    ax.axhline(
        mature["repeat_90d_customers"].sum() / mature["eligible_90d"].sum() * 100,
        color="#64748B",
        linestyle="--",
        label="Weighted mature-cohort average",
    )
    ax.set(title="90-day repeat rate by acquisition cohort", xlabel="First-purchase month", ylabel="Repeat rate (%)")
    ax.tick_params(axis="x", rotation=55, labelsize=9)
    ax.legend(frameon=False, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    save("02_cohort_repeat_90d.png")

    segments = pd.read_csv(TABLES / "rfm_segment_summary.csv").sort_values("net_value_share", ascending=True)
    y = np.arange(len(segments))
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.barh(y - 0.18, segments["customer_share"] * 100, height=0.35, color=blue, label="Customer share")
    ax.barh(y + 0.18, segments["net_value_share"] * 100, height=0.35, color=amber, label="Net revenue share")
    ax.set_yticks(y, segments["segment"])
    ax.set(title="RFM segment size and historical value", xlabel="Share (%)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    save("03_rfm_segment_shares.png")

    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    sizes = 80 + segments["customers"] / segments["customers"].max() * 900
    scatter = ax.scatter(
        segments["avg_recency_days"],
        segments["avg_monetary_value"],
        s=sizes,
        c=segments["net_value_share"],
        cmap="Blues",
        alpha=0.8,
        edgecolor="white",
        linewidth=1.2,
    )
    for _, row in segments.iterrows():
        ax.annotate(row["segment"], (row["avg_recency_days"], row["avg_monetary_value"]), xytext=(5, 5), textcoords="offset points", fontsize=9)
    ax.set(title="Operational priority map", xlabel="Average recency (days)", ylabel="Average gross purchase value")
    fig.colorbar(scatter, ax=ax, label="Net revenue share")
    ax.spines[["top", "right"]].set_visible(False)
    save("04_action_priority_map.png")

    print(f"FIGURES_OK count={len(list(FIGURES.glob('*.png')))} path={FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
