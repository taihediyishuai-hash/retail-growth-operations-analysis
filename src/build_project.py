#!/usr/bin/env python3
"""Build the reproducible data layer for the retail operations portfolio."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "online_retail_II.csv"
PROCESSED = ROOT / "data" / "processed"
RUN = ROOT / "outputs" / "run_20260915"
TABLES = RUN / "tables"
FIGURES = RUN / "figures"
DATABASE = PROCESSED / "retail_operations.db"
REFERENCE_DATE = pd.Timestamp("2011-12-10")
OBSERVATION_START = pd.Timestamp("2009-12-01 07:45:00")
OBSERVATION_END = pd.Timestamp("2011-12-09 12:50:00")
HISTORY_WASHOUT_DAYS = 90

NON_PRODUCT_CODES = {
    "M", "D", "POST", "DOT", "C2", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "PADS", "S", "B", "ADJUST", "ADJUST2", "TEST001", "TEST002",
}
DUPLICATE_KEY = [
    "invoice_id", "stock_code", "quantity", "order_ts", "unit_price", "customer_id"
]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_and_clean() -> tuple[pd.DataFrame, dict]:
    frame = pd.read_csv(
        RAW,
        dtype={"Invoice": "string", "StockCode": "string", "Description": "string", "Country": "string"},
        parse_dates=["InvoiceDate"],
    ).rename(
        columns={
            "Invoice": "invoice_id",
            "StockCode": "stock_code",
            "Description": "description",
            "Quantity": "quantity",
            "InvoiceDate": "order_ts",
            "Price": "unit_price",
            "Customer ID": "customer_id",
            "Country": "country",
        }
    )
    source_rows = len(frame)
    source_duplicate_rows = int(frame.duplicated().sum())
    source_customer_missing = int(frame["customer_id"].isna().sum())
    frame["invoice_id"] = frame["invoice_id"].str.strip()
    frame["stock_code"] = frame["stock_code"].str.strip()
    frame["country"] = frame["country"].str.strip()
    frame["customer_id"] = pd.to_numeric(frame["customer_id"], errors="coerce").astype("Int64")

    non_product_mask = frame["stock_code"].isin(NON_PRODUCT_CODES)
    invalid_value_mask = (frame["quantity"] == 0) | (frame["unit_price"] <= 0)
    eligible = frame.loc[~non_product_mask & ~invalid_value_mask].copy()
    duplicate_mask = eligible.duplicated(subset=DUPLICATE_KEY, keep="first")
    eligible["order_day_for_sensitivity"] = eligible["order_ts"].dt.normalize()
    day_level_key = [
        "invoice_id", "stock_code", "quantity", "order_day_for_sensitivity", "unit_price", "customer_id"
    ]
    day_level_duplicate_mask = eligible.duplicated(subset=day_level_key, keep="first")
    ambiguous_near_duplicate_mask = day_level_duplicate_mask & ~duplicate_mask

    cleaning = {
        "source_rows": source_rows,
        "source_duplicate_rows_all_columns": source_duplicate_rows,
        "source_customer_id_missing_rows": source_customer_missing,
        "source_customer_id_missing_rate": source_customer_missing / source_rows,
        "excluded_non_product_rows": int(non_product_mask.sum()),
        "excluded_non_product_amount": float(
            (frame.loc[non_product_mask, "quantity"] * frame.loc[non_product_mask, "unit_price"]).sum()
        ),
        "excluded_zero_quantity_or_nonpositive_price_rows": int(invalid_value_mask.sum()),
        "excluded_duplicate_rows_after_basic_filters": int(duplicate_mask.sum()),
        "excluded_duplicate_amount": float(
            (eligible.loc[duplicate_mask, "quantity"] * eligible.loc[duplicate_mask, "unit_price"]).sum()
        ),
        "ambiguous_same_day_different_timestamp_rows_kept": int(ambiguous_near_duplicate_mask.sum()),
        "ambiguous_same_day_different_timestamp_amount_kept": float(
            (
                eligible.loc[ambiguous_near_duplicate_mask, "quantity"]
                * eligible.loc[ambiguous_near_duplicate_mask, "unit_price"]
            ).sum()
        ),
        "duplicate_policy": "仅删除六列键完全相同且时间戳也相同的行；同发票同商品但时间戳不同的 2 行保留",
    }
    cleaned = eligible.loc[~duplicate_mask].copy()
    cleaned["line_amount"] = cleaned["quantity"] * cleaned["unit_price"]
    cleaned["gross_sales_component"] = cleaned["line_amount"].where(cleaned["quantity"] > 0, 0.0)
    cleaned["return_amount_component"] = (-cleaned["line_amount"]).where(cleaned["quantity"] < 0, 0.0)
    cleaned["sales_items_component"] = cleaned["quantity"].where(cleaned["quantity"] > 0, 0)
    cleaned["return_items_component"] = (-cleaned["quantity"]).where(cleaned["quantity"] < 0, 0)
    cleaning.update(
        {
            "cleaned_rows": len(cleaned),
            "cleaned_row_retention_rate": len(cleaned) / source_rows,
            "cleaned_customer_id_missing_rows": int(cleaned["customer_id"].isna().sum()),
            "cleaned_customer_id_missing_rate": float(cleaned["customer_id"].isna().mean()),
            "date_min": cleaned["order_ts"].min().isoformat(),
            "date_max": cleaned["order_ts"].max().isoformat(),
        }
    )
    return cleaned, cleaning


def build_orders(cleaned: pd.DataFrame) -> pd.DataFrame:
    orders = (
        cleaned.groupby("invoice_id", observed=True)
        .agg(
            order_ts=("order_ts", "min"),
            order_ts_max=("order_ts", "max"),
            timestamp_value_count=("order_ts", "nunique"),
            customer_id=("customer_id", "first"),
            customer_id_value_count=("customer_id", "nunique"),
            customer_id_missing_lines=("customer_id", lambda values: int(values.isna().sum())),
            country=("country", "first"),
            country_value_count=("country", "nunique"),
            gross_sales=("gross_sales_component", "sum"),
            return_amount=("return_amount_component", "sum"),
            net_revenue=("line_amount", "sum"),
            sales_items=("sales_items_component", "sum"),
            return_items=("return_items_component", "sum"),
            distinct_products=("stock_code", "nunique"),
            line_count=("stock_code", "size"),
        )
        .reset_index()
    )
    orders["timestamp_span_minutes"] = (
        orders["order_ts_max"] - orders["order_ts"]
    ).dt.total_seconds() / 60
    orders["customer_id_conflict"] = orders["customer_id_value_count"] > 1
    orders.loc[orders["customer_id_conflict"], "customer_id"] = pd.NA
    orders["country_conflict"] = orders["country_value_count"] > 1
    orders.loc[orders["country_conflict"], "country"] = "Multiple"
    orders["is_sale_order"] = orders["gross_sales"] > 0
    orders["is_return_order"] = orders["return_amount"] > 0
    orders["order_date"] = orders["order_ts"].dt.date.astype(str)
    orders["order_month"] = orders["order_ts"].dt.to_period("M").astype(str)
    money = ["gross_sales", "return_amount", "net_revenue"]
    orders[money] = orders[money].round(2)
    return orders


def build_monthly(cleaned: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    lines = cleaned.copy()
    lines["month"] = lines["order_ts"].dt.to_period("M").astype(str)
    monthly = (
        lines.groupby("month", observed=True)
        .agg(
            gross_sales=("gross_sales_component", "sum"),
            return_amount=("return_amount_component", "sum"),
            net_revenue=("line_amount", "sum"),
            sales_items=("sales_items_component", "sum"),
            return_items=("return_items_component", "sum"),
        )
        .reset_index()
    )

    sales_orders = orders.loc[orders["is_sale_order"]].copy()
    customers = sales_orders.loc[sales_orders["customer_id"].notna()].copy()
    first_month = customers.groupby("customer_id")["order_ts"].min().dt.to_period("M").astype(str)
    customers["first_month"] = customers["customer_id"].map(first_month)

    order_counts = sales_orders.groupby("order_month")["invoice_id"].nunique().rename("sale_orders")
    active = customers.groupby("order_month")["customer_id"].nunique().rename("active_customers")
    new = (
        customers.loc[customers["order_month"] == customers["first_month"]]
        .groupby("order_month")["customer_id"]
        .nunique()
        .rename("new_customers")
    )
    repeat = (
        customers.loc[customers["order_month"] > customers["first_month"]]
        .groupby("order_month")["customer_id"]
        .nunique()
        .rename("returning_customers")
    )
    monthly = monthly.merge(order_counts, left_on="month", right_index=True, how="left")
    monthly = monthly.merge(active, left_on="month", right_index=True, how="left")
    monthly = monthly.merge(new, left_on="month", right_index=True, how="left")
    monthly = monthly.merge(repeat, left_on="month", right_index=True, how="left")
    for field in ["sale_orders", "active_customers", "new_customers", "returning_customers"]:
        monthly[field] = monthly[field].fillna(0).astype(int)
    monthly["gross_aov"] = monthly["gross_sales"] / monthly["sale_orders"]
    monthly["return_amount_rate"] = monthly["return_amount"] / monthly["gross_sales"]
    monthly["returning_customer_share"] = monthly["returning_customers"] / monthly["active_customers"]
    monthly["is_complete_month"] = monthly["month"] != "2011-12"
    for field in ["gross_sales", "return_amount", "net_revenue", "gross_aov"]:
        monthly[field] = monthly[field].round(2)
    for field in ["return_amount_rate", "returning_customer_share"]:
        monthly[field] = monthly[field].round(6)
    return monthly


def build_repeat_metrics(orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    sales = orders.loc[orders["is_sale_order"] & orders["customer_id"].notna()].copy()
    sales = sales.sort_values(["customer_id", "order_ts", "invoice_id"])
    first_ts = sales.groupby("customer_id")["order_ts"].min().rename("first_order_ts")
    sales = sales.join(first_ts, on="customer_id")
    later = sales.loc[sales["order_ts"] > sales["first_order_ts"]]
    second_ts = later.groupby("customer_id")["order_ts"].min().rename("second_order_ts")

    customers = first_ts.to_frame().join(second_ts, how="left").reset_index()
    customers["days_to_second_order"] = (
        customers["second_order_ts"] - customers["first_order_ts"]
    ).dt.total_seconds() / 86400
    customers["cohort_month"] = customers["first_order_ts"].dt.to_period("M").astype(str)
    customers["cohort_quarter"] = customers["first_order_ts"].dt.to_period("Q").astype(str)
    customers["history_observable"] = (
        customers["first_order_ts"] >= OBSERVATION_START + pd.Timedelta(days=HISTORY_WASHOUT_DAYS)
    )

    for days in (30, 60, 90):
        customers[f"eligible_{days}d"] = (
            customers["history_observable"]
            & (customers["first_order_ts"] <= OBSERVATION_END - pd.Timedelta(days=days))
        )
        customers[f"repeated_{days}d"] = (
            customers[f"eligible_{days}d"]
            & customers["days_to_second_order"].notna()
            & (customers["days_to_second_order"] <= days)
        )

    rows = []
    for cohort_month, group in customers.groupby("cohort_month", sort=True):
        row: dict[str, object] = {
            "cohort_month": cohort_month,
            "cohort_size": len(group),
            "history_observable_customers": int(group["history_observable"].sum()),
        }
        for days in (30, 60, 90):
            eligible = group[f"eligible_{days}d"]
            denominator = int(eligible.sum())
            numerator = int(group.loc[eligible, f"repeated_{days}d"].sum())
            row[f"eligible_{days}d"] = denominator
            row[f"repeat_{days}d_customers"] = numerator
            row[f"repeat_{days}d_rate"] = numerator / denominator if denominator else np.nan
            row[f"mature_{days}d"] = denominator == len(group)
        rows.append(row)
    cohort = pd.DataFrame(rows)
    rate_fields = [field for field in cohort.columns if field.endswith("_rate")]
    cohort[rate_fields] = cohort[rate_fields].round(6)

    eligible = customers["eligible_90d"]
    repeat_summary = {
        "customers_with_id": int(len(customers)),
        "eligible_90d_customers": int(eligible.sum()),
        "repeat_90d_customers": int(customers.loc[eligible, "repeated_90d"].sum()),
        "repeat_90d_rate": float(customers.loc[eligible, "repeated_90d"].mean()),
        "observation_end": OBSERVATION_END.isoformat(),
        "history_washout_days": HISTORY_WASHOUT_DAYS,
        "left_censored_customers_excluded": int((~customers["history_observable"]).sum()),
        "definition": "首笔可观测购买前有 90 天历史洗脱、其后有完整 90 天观察窗的客户中，90 天内出现第二张更晚的正向商品发票",
    }
    return customers, cohort, repeat_summary


def qscore(series: pd.Series, higher_is_better: bool) -> pd.Series:
    rank = series.rank(method="first")
    scores = pd.qcut(rank, 5, labels=[1, 2, 3, 4, 5]).astype(int)
    return scores if higher_is_better else 6 - scores


def label_segment(row: pd.Series) -> str:
    if row["frequency_orders"] < 2:
        return "One-time"
    r, f, m = int(row["r_score"]), int(row["f_score"]), int(row["m_score"])
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 4 and m >= 3:
        return "Loyal"
    if r >= 4 and f <= 3:
        return "New & promising"
    if r <= 2 and f >= 3 and m >= 3:
        return "At risk"
    if r <= 2 and f <= 2 and m <= 2:
        return "Hibernating"
    if r == 3 and f <= 3:
        return "Needs attention"
    return "Potential loyalist"


def build_rfm(cleaned: pd.DataFrame, orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    sales = orders.loc[orders["is_sale_order"] & orders["customer_id"].notna()].copy()
    gross = sales.groupby("customer_id").agg(
        last_purchase_ts=("order_ts", "max"),
        first_purchase_ts=("order_ts", "min"),
        frequency_orders=("invoice_id", "nunique"),
        gross_purchase_value=("gross_sales", "sum"),
    )
    net = (
        cleaned.loc[cleaned["customer_id"].notna()]
        .groupby("customer_id")["line_amount"]
        .sum()
        .rename("net_customer_revenue")
    )
    rfm = gross.join(net, how="left").reset_index()
    rfm["recency_days"] = (REFERENCE_DATE - rfm["last_purchase_ts"].dt.normalize()).dt.days
    rfm["monetary_value"] = rfm["net_customer_revenue"].clip(lower=0)
    rfm["monetary_for_score"] = rfm["monetary_value"].clip(
        lower=rfm["monetary_value"].quantile(0.01), upper=rfm["monetary_value"].quantile(0.99)
    )
    rfm["r_score"] = qscore(rfm["recency_days"], higher_is_better=False)
    rfm["f_score"] = qscore(rfm["frequency_orders"], higher_is_better=True)
    rfm["m_score"] = qscore(rfm["monetary_for_score"], higher_is_better=True)
    rfm["rfm_score"] = rfm["r_score"] * 100 + rfm["f_score"] * 10 + rfm["m_score"]
    rfm["segment"] = rfm.apply(label_segment, axis=1)

    summary = (
        rfm.groupby("segment", observed=True)
        .agg(
            customers=("customer_id", "nunique"),
            gross_purchase_value=("gross_purchase_value", "sum"),
            net_customer_revenue=("net_customer_revenue", "sum"),
            avg_recency_days=("recency_days", "mean"),
            avg_frequency_orders=("frequency_orders", "mean"),
            avg_monetary_value=("monetary_value", "mean"),
        )
        .reset_index()
    )
    summary["customer_share"] = summary["customers"] / summary["customers"].sum()
    summary["gross_value_share"] = summary["gross_purchase_value"] / summary["gross_purchase_value"].sum()
    summary["net_value_share"] = summary["net_customer_revenue"] / summary["net_customer_revenue"].sum()
    summary = summary.sort_values("net_customer_revenue", ascending=False).reset_index(drop=True)
    summary[["gross_purchase_value", "net_customer_revenue", "avg_monetary_value"]] = summary[
        ["gross_purchase_value", "net_customer_revenue", "avg_monetary_value"]
    ].round(2)
    summary[["avg_recency_days", "avg_frequency_orders"]] = summary[
        ["avg_recency_days", "avg_frequency_orders"]
    ].round(2)
    summary[["customer_share", "gross_value_share", "net_value_share"]] = summary[
        ["customer_share", "gross_value_share", "net_value_share"]
    ].round(6)

    cutoffs = {
        "reference_date": REFERENCE_DATE.date().isoformat(),
        "entity_count": int(len(rfm)),
        "single_purchase_customers": int((rfm["frequency_orders"] < 2).sum()),
        "single_purchase_share": float((rfm["frequency_orders"] < 2).mean()),
        "recency_quantiles_days": [float(x) for x in rfm["recency_days"].quantile([0.2, 0.4, 0.6, 0.8])],
        "frequency_quantiles_orders": [float(x) for x in rfm["frequency_orders"].quantile([0.2, 0.4, 0.6, 0.8])],
        "monetary_quantiles_net_revenue": [float(x) for x in rfm["monetary_value"].quantile([0.2, 0.4, 0.6, 0.8])],
        "winsor_limits_monetary": [
            float(rfm["monetary_value"].quantile(0.01)),
            float(rfm["monetary_value"].quantile(0.99)),
        ],
        "limitations": [
            "RFM 是历史价值描述，不预测营销响应率；M 使用客户净收入并把负值截为 0 后评分",
            "单次购买客户单列为 One-time，不把一次交易强行解释为稳定 RFM 行为",
            "客户编号缺失的交易不进入 RFM",
        ],
    }
    return rfm, summary, cutoffs


def build_country_summary(orders: pd.DataFrame) -> pd.DataFrame:
    return (
        orders.groupby("country", observed=True)
        .agg(
            net_revenue=("net_revenue", "sum"),
            gross_sales=("gross_sales", "sum"),
            return_amount=("return_amount", "sum"),
            sale_orders=("is_sale_order", "sum"),
            customers=("customer_id", "nunique"),
        )
        .reset_index()
        .sort_values("net_revenue", ascending=False)
        .assign(
            net_revenue=lambda x: x["net_revenue"].round(2),
            gross_sales=lambda x: x["gross_sales"].round(2),
            return_amount=lambda x: x["return_amount"].round(2),
        )
    )


def add_action_plan(segment_summary: pd.DataFrame) -> pd.DataFrame:
    actions = {
        "At risk": (1, "高历史价值沉默召回", "随机保留对照组；比较 30 天回购率与净收入/触达客户"),
        "One-time": (2, "首笔可观测购买后第二单培育", "按该笔购买后 7/14 天随机分组并保留不触达对照；比较 90 天复购率"),
        "Champions": (3, "忠诚维护与流失预警", "监控 30 天未购占比、复购间隔和退货金额率"),
        "Loyal": (4, "稳定复购维护", "比较触达前后购买间隔，并保留随机对照"),
        "New & promising": (5, "新客 onboarding", "比较 30/60/90 天第二单率"),
        "Potential loyalist": (6, "培育购买频次", "比较订单频次与客单价护栏"),
        "Needs attention": (7, "低成本提醒", "设置触达频控，以净收入和退订率为护栏"),
        "Hibernating": (8, "控制触达成本", "仅在预估毛利覆盖触达成本时进入实验"),
    }
    output = segment_summary.copy()
    output[["priority", "proposed_action", "validation_plan"]] = output["segment"].apply(
        lambda value: pd.Series(actions[value])
    )
    return output.sort_values("priority")


def persist_database(tables: dict[str, pd.DataFrame]) -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    if DATABASE.exists():
        DATABASE.unlink()
    with sqlite3.connect(DATABASE) as connection:
        for name, frame in tables.items():
            sql_frame = frame.copy()
            for field in sql_frame.select_dtypes(include=["datetime64[ns]"]).columns:
                sql_frame[field] = sql_frame[field].dt.strftime("%Y-%m-%d %H:%M:%S")
            for field in sql_frame.columns:
                if str(sql_frame[field].dtype) == "Int64":
                    sql_frame[field] = sql_frame[field].astype(object).where(sql_frame[field].notna(), None)
            sql_frame.to_sql(name, connection, index=False, if_exists="replace")
        connection.execute("CREATE INDEX idx_orders_customer_time ON orders(customer_id, order_ts)")
        connection.execute("CREATE INDEX idx_orders_month ON orders(order_month)")


def main() -> int:
    for directory in (PROCESSED, TABLES, FIGURES):
        directory.mkdir(parents=True, exist_ok=True)
    if not RAW.is_file():
        raise SystemExit("Raw data missing. Run: python src/download_data.py")

    cleaned, cleaning = load_and_clean()
    orders = build_orders(cleaned)
    monthly = build_monthly(cleaned, orders)
    repeat_customers, cohort_repeat, repeat_summary = build_repeat_metrics(orders)
    rfm, rfm_summary, rfm_cutoffs = build_rfm(cleaned, orders)
    country_summary = build_country_summary(orders)
    action_plan = add_action_plan(rfm_summary)

    orders.to_csv(PROCESSED / "orders.csv", index=False)
    monthly.to_csv(TABLES / "monthly_kpis.csv", index=False)
    cohort_repeat.to_csv(TABLES / "cohort_repeat.csv", index=False)
    rfm.to_csv(TABLES / "customer_rfm.csv", index=False)
    rfm_summary.to_csv(TABLES / "rfm_segment_summary.csv", index=False)
    country_summary.to_csv(TABLES / "country_summary.csv", index=False)
    action_plan.to_csv(TABLES / "action_plan.csv", index=False)

    additive = monthly[
        ["month", "gross_sales", "return_amount", "net_revenue", "sales_items", "return_items", "sale_orders", "new_customers"]
    ].copy()
    total = {"month": "合计"}
    for field in additive.columns[1:]:
        total[field] = float(additive[field].sum())
    monthly_with_total = pd.concat([additive, pd.DataFrame([total])], ignore_index=True)
    monthly_with_total.to_csv(TABLES / "monthly_kpis_with_total.csv", index=False)

    persist_database(
        {
            "orders": orders,
            "monthly_kpis": monthly,
            "cohort_repeat": cohort_repeat,
            "customer_rfm": rfm,
            "rfm_segment_summary": rfm_summary,
            "country_summary": country_summary,
            "action_plan": action_plan,
        }
    )

    complete = monthly.loc[monthly["is_complete_month"]].copy()
    metrics = {
        "cleaning": cleaning,
        "orders": {
            "order_rows": int(len(orders)),
            "sale_orders": int(orders["is_sale_order"].sum()),
            "return_orders": int(orders["is_return_order"].sum()),
            "customers_with_id": int(orders["customer_id"].nunique()),
            "invoices_with_multiple_timestamps": int((orders["timestamp_value_count"] > 1).sum()),
            "max_timestamp_span_minutes": float(orders["timestamp_span_minutes"].max()),
            "invoices_with_customer_id_conflict": int(orders["customer_id_conflict"].sum()),
            "invoices_with_country_conflict": int(orders["country_conflict"].sum()),
        },
        "financial": {
            "gross_sales": float(cleaned["gross_sales_component"].sum()),
            "return_amount": float(cleaned["return_amount_component"].sum()),
            "net_revenue": float(cleaned["line_amount"].sum()),
            "return_amount_rate": float(cleaned["return_amount_component"].sum() / cleaned["gross_sales_component"].sum()),
        },
        "monthly": {
            "complete_months": int(len(complete)),
            "highest_net_revenue_month": str(complete.loc[complete["net_revenue"].idxmax(), "month"]),
            "highest_net_revenue": float(complete["net_revenue"].max()),
            "lowest_net_revenue_month": str(complete.loc[complete["net_revenue"].idxmin(), "month"]),
            "lowest_net_revenue": float(complete["net_revenue"].min()),
        },
        "repeat": repeat_summary,
        "rfm": rfm_cutoffs,
        "top_segments": action_plan.head(4).to_dict(orient="records"),
        "limitations": [
            "客户编号缺失交易保留在全盘收入，但不进入复购和 RFM",
            "数据没有营销触达、成本和随机对照，策略效果未实际验证",
            "2011-12 只有 9 天，月度极值比较排除该不完整月",
            "公开数据来自一家英国零售商，不能直接外推到其他行业或企业",
        ],
    }
    write_json(RUN / "cleaning_report.json", cleaning)
    write_json(RUN / "analysis_metrics.json", metrics)
    write_json(RUN / "rfm_cutoffs.json", rfm_cutoffs)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
