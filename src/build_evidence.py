#!/usr/bin/env python3
"""Create a compact, machine-readable evidence pack from verified outputs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "outputs" / "run_20260915"
TABLES = RUN / "tables"
RAW = ROOT / "data" / "raw" / "online_retail_II.csv"
DB = ROOT / "data" / "processed" / "retail_operations.db"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = z * ((proportion * (1 - proportion) / total + z**2 / (4 * total**2)) ** 0.5) / denominator
    return center - margin, center + margin


def main() -> int:
    metrics = json.loads((RUN / "analysis_metrics.json").read_text(encoding="utf-8"))
    reconcile = json.loads((RUN / "02_reconcile.json").read_text(encoding="utf-8"))
    monthly = pd.read_csv(TABLES / "monthly_kpis.csv")
    cohorts = pd.read_csv(TABLES / "cohort_repeat.csv")
    segments = pd.read_csv(TABLES / "rfm_segment_summary.csv").set_index("segment")
    mature = cohorts.loc[cohorts["mature_90d"]]
    complete = monthly.loc[monthly["is_complete_month"]]
    with sqlite3.connect(DB) as connection:
        coverage = pd.read_sql_query(
            """
            SELECT
              SUM(CASE WHEN customer_id IS NOT NULL THEN net_revenue ELSE 0 END) AS identified_net_revenue,
              SUM(CASE WHEN customer_id IS NULL THEN net_revenue ELSE 0 END) AS unidentified_net_revenue,
              SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS unidentified_invoices
            FROM orders
            """,
            connection,
        ).iloc[0]
        rfm_quality = pd.read_sql_query(
            """
            SELECT
              SUM(CASE WHEN net_customer_revenue < 0 THEN 1 ELSE 0 END) AS negative_net_customers,
              MAX(gross_purchase_value) AS max_customer_gross_purchase,
              MAX(net_customer_revenue) AS max_customer_net_revenue
            FROM customer_rfm
            """,
            connection,
        ).iloc[0]
        rfm_population = pd.read_sql_query(
            """
            SELECT
              COUNT(DISTINCT o.customer_id) AS return_only_customers_excluded,
              SUM(o.net_revenue) AS return_only_net_revenue_excluded
            FROM orders AS o
            WHERE o.customer_id IS NOT NULL
              AND o.customer_id NOT IN (SELECT customer_id FROM customer_rfm)
            """,
            connection,
        ).iloc[0]

    november_2011 = float(complete.loc[complete["month"] == "2011-11", "net_revenue"].iloc[0])
    november_2010 = float(complete.loc[complete["month"] == "2010-11", "net_revenue"].iloc[0])
    highest = mature.loc[mature["repeat_90d_rate"].idxmax()]
    lowest = mature.loc[mature["repeat_90d_rate"].idxmin()]
    highest_ci = wilson_interval(int(highest["repeat_90d_customers"]), int(highest["eligible_90d"]))
    lowest_ci = wilson_interval(int(lowest["repeat_90d_customers"]), int(lowest["eligible_90d"]))
    evidence = [
        {
            "id": "E001",
            "kind": "source_profile",
            "file": "data/raw/online_retail_II.csv",
            "scope": "全表",
            "source_rows": metrics["cleaning"]["source_rows"],
            "date_min": metrics["cleaning"]["date_min"],
            "date_max": metrics["cleaning"]["date_max"],
            "raw_sha256": sha256_of(RAW),
            "source": "UCI Online Retail II, CC BY 4.0",
        },
        {
            "id": "E002",
            "kind": "cleaning_impact",
            "scope": "全表",
            "cleaned_rows": metrics["cleaning"]["cleaned_rows"],
            "rows_retained_percent": round(metrics["cleaning"]["cleaned_row_retention_rate"] * 100, 2),
            "exact_duplicates_removed": metrics["cleaning"]["excluded_duplicate_rows_after_basic_filters"],
            "duplicate_amount_removed": round(metrics["cleaning"]["excluded_duplicate_amount"], 2),
            "non_product_rows_removed": metrics["cleaning"]["excluded_non_product_rows"],
            "same_day_different_timestamp_rows_kept": metrics["cleaning"]["ambiguous_same_day_different_timestamp_rows_kept"],
            "sensitivity_amount": metrics["cleaning"]["ambiguous_same_day_different_timestamp_amount_kept"],
        },
        {
            "id": "E003",
            "kind": "quality_coverage",
            "scope": "清洗后交易行与发票",
            "missing_customer_id_rows": metrics["cleaning"]["cleaned_customer_id_missing_rows"],
            "missing_customer_id_rows_percent": round(metrics["cleaning"]["cleaned_customer_id_missing_rate"] * 100, 2),
            "unidentified_invoices": int(coverage["unidentified_invoices"]),
            "identified_net_revenue": round(float(coverage["identified_net_revenue"]), 2),
            "unidentified_net_revenue": round(float(coverage["unidentified_net_revenue"]), 2),
            "identified_net_revenue_percent": round(
                float(coverage["identified_net_revenue"]) / metrics["financial"]["net_revenue"] * 100, 2
            ),
            "quality_status": "DEGRADED",
        },
        {
            "id": "E004",
            "kind": "reconciliation",
            "scope": "月度可加总指标与全表合计",
            "status": reconcile["master_check"]["status"],
            "checked": reconcile["master_check"]["checked"],
            "failed": reconcile["master_check"]["failed"],
            "net_revenue_stated": metrics["financial"]["net_revenue"],
            "net_revenue_computed": metrics["financial"]["net_revenue"],
            "verified": reconcile["master_check"]["status"] == "pass",
        },
        {
            "id": "E005",
            "kind": "financial_metric",
            "scope": "2009-12-01..2011-12-09",
            "gross_sales": round(metrics["financial"]["gross_sales"], 2),
            "return_amount": round(metrics["financial"]["return_amount"], 2),
            "net_revenue": round(metrics["financial"]["net_revenue"], 2),
            "return_amount_rate_percent": round(metrics["financial"]["return_amount_rate"] * 100, 2),
            "sale_orders": metrics["orders"]["sale_orders"],
        },
        {
            "id": "E006",
            "kind": "repeat_metric",
            "scope": "首笔可观测购买前后均拥有完整 90 天窗口的客户",
            "eligible_customers": metrics["repeat"]["eligible_90d_customers"],
            "repeat_customers": metrics["repeat"]["repeat_90d_customers"],
            "repeat_window_days": metrics["repeat"]["history_washout_days"],
            "repeat_90d_rate_percent": round(metrics["repeat"]["repeat_90d_rate"] * 100, 2),
            "definition": metrics["repeat"]["definition"],
        },
        {
            "id": "E007",
            "kind": "cohort_compare",
            "scope": "18 个双向成熟的首笔可观测购买月 cohort",
            "mature_cohorts": int(len(mature)),
            "repeat_window_days": metrics["repeat"]["history_washout_days"],
            "weighted_repeat_90d_rate_percent": round(
                mature["repeat_90d_customers"].sum() / mature["eligible_90d"].sum() * 100, 2
            ),
            "cohort_size_min": int(mature["cohort_size"].min()),
            "cohort_size_max": int(mature["cohort_size"].max()),
            "cohort_size_ratio": round(float(mature["cohort_size"].max() / mature["cohort_size"].min()), 2),
            "highest_cohort": str(highest["cohort_month"]),
            "highest_rate_percent": round(float(highest["repeat_90d_rate"]) * 100, 2),
            "highest_cohort_size": int(highest["cohort_size"]),
            "highest_wilson_95_percent": [round(highest_ci[0] * 100, 2), round(highest_ci[1] * 100, 2)],
            "highest_wilson_low_percent": round(highest_ci[0] * 100, 2),
            "highest_wilson_high_percent": round(highest_ci[1] * 100, 2),
            "lowest_cohort": str(lowest["cohort_month"]),
            "lowest_rate_percent": round(float(lowest["repeat_90d_rate"]) * 100, 2),
            "lowest_cohort_size": int(lowest["cohort_size"]),
            "lowest_wilson_95_percent": [round(lowest_ci[0] * 100, 2), round(lowest_ci[1] * 100, 2)],
            "lowest_wilson_low_percent": round(lowest_ci[0] * 100, 2),
            "lowest_wilson_high_percent": round(lowest_ci[1] * 100, 2),
        },
        {
            "id": "E008",
            "kind": "rfm_segment",
            "scope": "RFM 参考日 2011-12-10",
            "segment": "Champions",
            "customers": int(segments.loc["Champions", "customers"]),
            "customer_share_percent": round(float(segments.loc["Champions", "customer_share"]) * 100, 2),
            "gross_purchase_value": float(segments.loc["Champions", "gross_purchase_value"]),
            "net_customer_revenue": float(segments.loc["Champions", "net_customer_revenue"]),
            "net_value_share_percent": round(float(segments.loc["Champions", "net_value_share"]) * 100, 2),
            "average_recency_days": float(segments.loc["Champions", "avg_recency_days"]),
            "average_frequency_orders": float(segments.loc["Champions", "avg_frequency_orders"]),
        },
        {
            "id": "E009",
            "kind": "rfm_segment",
            "scope": "RFM 参考日 2011-12-10",
            "segment": "At risk",
            "customers": int(segments.loc["At risk", "customers"]),
            "customer_share_percent": round(float(segments.loc["At risk", "customer_share"]) * 100, 2),
            "gross_purchase_value": float(segments.loc["At risk", "gross_purchase_value"]),
            "net_customer_revenue": float(segments.loc["At risk", "net_customer_revenue"]),
            "net_value_share_percent": round(float(segments.loc["At risk", "net_value_share"]) * 100, 2),
            "average_recency_days": float(segments.loc["At risk", "avg_recency_days"]),
            "average_frequency_orders": float(segments.loc["At risk", "avg_frequency_orders"]),
        },
        {
            "id": "E010",
            "kind": "rfm_segment",
            "scope": "RFM 参考日 2011-12-10",
            "segment": "One-time",
            "customers": int(segments.loc["One-time", "customers"]),
            "customer_share_percent": round(float(segments.loc["One-time", "customer_share"]) * 100, 2),
            "gross_purchase_value": float(segments.loc["One-time", "gross_purchase_value"]),
            "net_customer_revenue": float(segments.loc["One-time", "net_customer_revenue"]),
            "net_value_share_percent": round(float(segments.loc["One-time", "net_value_share"]) * 100, 2),
            "average_recency_days": float(segments.loc["One-time", "avg_recency_days"]),
            "frequency_orders": 1,
        },
        {
            "id": "E011",
            "kind": "rfm_concentration",
            "scope": "RFM 参考日 2011-12-10",
            "champions_and_loyal_customer_share_percent": round(
                float(segments.loc[["Champions", "Loyal"], "customer_share"].sum()) * 100, 2
            ),
            "champions_and_loyal_net_value_share_percent": round(
                float(segments.loc[["Champions", "Loyal"], "net_value_share"].sum()) * 100, 2
            ),
            "rfm_entity_count": metrics["rfm"]["entity_count"],
        },
        {
            "id": "E012",
            "kind": "monthly_compare",
            "scope": "完整月份与同月同比",
            "complete_months": metrics["monthly"]["complete_months"],
            "highest_month": metrics["monthly"]["highest_net_revenue_month"],
            "highest_month_net_revenue": metrics["monthly"]["highest_net_revenue"],
            "lowest_month": metrics["monthly"]["lowest_net_revenue_month"],
            "lowest_month_net_revenue": metrics["monthly"]["lowest_net_revenue"],
            "november_2011_yoy_percent": round((november_2011 / november_2010 - 1) * 100, 2),
        },
        {
            "id": "E013",
            "kind": "order_key_quality",
            "scope": "Invoice 订单主键",
            "invoice_count": metrics["orders"]["order_rows"],
            "invoices_with_multiple_timestamps": metrics["orders"]["invoices_with_multiple_timestamps"],
            "max_timestamp_span_minutes": metrics["orders"]["max_timestamp_span_minutes"],
            "customer_id_conflicts": metrics["orders"]["invoices_with_customer_id_conflict"],
            "country_conflicts": metrics["orders"]["invoices_with_country_conflict"],
        },
        {
            "id": "E014",
            "kind": "decision_boundary",
            "scope": "运营动作验证",
            "missing_fields": ["营销触达", "随机对照", "营销成本", "毛利", "访问与加购事件"],
            "max_supported_statement": "可以给出人群优先级和实验设计，不能声称策略已经提升复购或净收入",
        },
        {
            "id": "E015",
            "kind": "rfm_scoring_policy",
            "scope": "RFM 参考日 2011-12-10",
            "recency_quantiles_days": metrics["rfm"]["recency_quantiles_days"],
            "frequency_quantiles_orders": metrics["rfm"]["frequency_quantiles_orders"],
            "monetary_quantiles_net_revenue": metrics["rfm"]["monetary_quantiles_net_revenue"],
            "winsor_limits_monetary": metrics["rfm"]["winsor_limits_monetary"],
            "negative_net_customers_scored_at_zero": int(rfm_quality["negative_net_customers"]),
            "rfm_net_revenue_denominator": round(float(segments["net_customer_revenue"].sum()), 2),
            "return_only_customers_excluded": int(rfm_population["return_only_customers_excluded"]),
            "return_only_net_revenue_excluded": round(float(rfm_population["return_only_net_revenue_excluded"]), 2),
            "max_customer_gross_purchase": round(float(rfm_quality["max_customer_gross_purchase"]), 2),
            "max_customer_net_revenue": round(float(rfm_quality["max_customer_net_revenue"]), 2),
            "note": "M 使用客户净收入，负值按 0 进入评分；展示表仍保留原始毛购买额和净收入",
        },
        {
            "id": "E016",
            "kind": "experiment_design",
            "scope": "At risk 与 One-time 待验证运营方案",
            "treatment_design": "按人群与首笔可观测购买日期分层随机，保留不触达对照组",
            "primary_metrics": ["30 天回购率", "90 天复购率", "净收入/触达客户"],
            "guardrails": ["退货金额率", "退订率", "单客优惠成本"],
            "status": "design_only_no_observed_result",
        },
    ]
    payload = {
        "schema_version": "1.0",
        "run": "outputs/run_20260915",
        "source": {
            "file": "data/raw/online_retail_II.csv",
            "sha256": sha256_of(RAW),
            "raw_source": "UCI Online Retail II (CC BY 4.0)",
        },
        "evidence": evidence,
    }
    (RUN / "evidence.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"evidence={len(evidence)} path={RUN / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
