"""Streamlit dashboard for the retail growth operations portfolio."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "outputs" / "run_20260915"
TABLES = RUN / "tables"


@st.cache_data
def load_outputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    return (
        pd.read_csv(TABLES / "monthly_kpis.csv"),
        pd.read_csv(TABLES / "cohort_repeat.csv"),
        pd.read_csv(TABLES / "rfm_segment_summary.csv"),
        pd.read_csv(TABLES / "action_plan.csv"),
        json.loads((RUN / "analysis_metrics.json").read_text(encoding="utf-8")),
    )


st.set_page_config(page_title="零售用户增长与复购运营分析", page_icon="📊", layout="wide")
monthly, cohort, segments, actions, metrics = load_outputs()

st.title("零售用户增长与复购运营分析")
st.caption("真实公开数据 · UCI Online Retail II · 个人项目 · 策略未真实投放")

col1, col2, col3, col4 = st.columns(4)
col1.metric("净收入", f"{metrics['financial']['net_revenue'] / 1_000_000:.2f}M")
col2.metric("正向订单", f"{metrics['orders']['sale_orders']:,}")
col3.metric("成熟客户 90 天复购率", f"{metrics['repeat']['repeat_90d_rate']:.2%}")
col4.metric("可识别购买客户", f"{metrics['repeat']['customers_with_id']:,}")

trend_tab, cohort_tab, segment_tab, quality_tab = st.tabs(["经营趋势", "复购同期群", "RFM 与运营动作", "数据质量"])

with trend_tab:
    st.subheader("完整月份净收入")
    complete = monthly.loc[monthly["is_complete_month"]].set_index("month")
    st.line_chart(complete[["net_revenue"]])
    st.dataframe(
        complete[["net_revenue", "sale_orders", "active_customers", "gross_aov", "return_amount_rate"]],
        width="stretch",
    )

with cohort_tab:
    st.subheader("首笔可观测购买后 90 天复购率")
    mature = cohort.loc[cohort["mature_90d"]].set_index("cohort_month")
    st.line_chart(mature[["repeat_90d_rate"]])
    st.caption("只展示整个月客户都拥有完整 90 天观察窗的 cohort；末端 cohort 不进入该图。")
    st.dataframe(cohort, width="stretch")

with segment_tab:
    st.subheader("人群规模与历史价值")
    share = segments.set_index("segment")[["customer_share", "net_value_share"]]
    st.bar_chart(share)
    st.dataframe(
        actions[["priority", "segment", "customers", "net_value_share", "proposed_action", "validation_plan"]],
        width="stretch",
        hide_index=True,
    )
    st.info("RFM 是历史行为分层，不预测营销响应。运营动作需要通过随机对照实验验证。")

with quality_tab:
    cleaning = metrics["cleaning"]
    st.subheader("质量门禁")
    st.json(
        {
            "原始行数": cleaning["source_rows"],
            "清洗后行数": cleaning["cleaned_rows"],
            "删除的完全重复行": cleaning["excluded_duplicate_rows_after_basic_filters"],
            "清洗后客户编号缺失率": cleaning["cleaned_customer_id_missing_rate"],
            "同日但时间戳不同且保留的近重复行": cleaning["ambiguous_same_day_different_timestamp_rows_kept"],
        }
    )
    st.warning("客户编号缺失的订单保留在全盘收入，但不进入复购和 RFM；2011-12 只有 9 天，不参与完整月比较。")
