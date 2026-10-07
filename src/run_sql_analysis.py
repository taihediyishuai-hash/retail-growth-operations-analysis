#!/usr/bin/env python3
"""Run portfolio SQL queries and save each result as a CSV."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "retail_operations.db"
OUT = ROOT / "outputs" / "run_20260915" / "sql_results"

QUERIES = {
    "01_monthly_operations": """
        SELECT month, ROUND(net_revenue, 2) AS net_revenue, sale_orders,
               active_customers, ROUND(gross_aov, 2) AS gross_aov,
               ROUND(return_amount_rate * 100, 2) AS return_amount_rate_pct,
               ROUND(returning_customer_share * 100, 2) AS returning_customer_share_pct
        FROM monthly_kpis WHERE is_complete_month = 1 ORDER BY month
    """,
    "02_mature_cohort_repeat": """
        SELECT cohort_month, cohort_size, repeat_90d_customers,
               ROUND(repeat_90d_rate * 100, 2) AS repeat_90d_rate_pct
        FROM cohort_repeat WHERE mature_90d = 1 ORDER BY cohort_month
    """,
    "03_rfm_segments": """
        SELECT segment, customers, ROUND(customer_share * 100, 2) AS customer_share_pct,
               ROUND(gross_purchase_value, 2) AS gross_purchase_value,
               ROUND(net_value_share * 100, 2) AS net_value_share_pct,
               avg_recency_days, avg_frequency_orders
        FROM rfm_segment_summary ORDER BY gross_purchase_value DESC
    """,
    "04_action_plan": """
        SELECT priority, segment, customers, ROUND(net_value_share * 100, 2) AS net_value_share_pct,
               proposed_action, validation_plan FROM action_plan ORDER BY priority
    """,
    "05_top_countries": """
        SELECT country, ROUND(net_revenue, 2) AS net_revenue, sale_orders, customers
        FROM country_summary ORDER BY net_revenue DESC LIMIT 10
    """,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as connection:
        for name, query in QUERIES.items():
            result = pd.read_sql_query(query, connection)
            result.to_csv(OUT / f"{name}.csv", index=False)
            print(f"{name}: {len(result)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
