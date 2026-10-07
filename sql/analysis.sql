-- 零售用户增长与复购运营分析
-- 数据库由 src/build_project.py 生成：data/processed/retail_operations.db

-- 1. 月度经营指标：净收入、订单量、活跃客户、回访客户占比
SELECT
    month,
    ROUND(net_revenue, 2) AS net_revenue,
    sale_orders,
    active_customers,
    ROUND(gross_aov, 2) AS gross_aov,
    ROUND(return_amount_rate * 100, 2) AS return_amount_rate_pct,
    ROUND(returning_customer_share * 100, 2) AS returning_customer_share_pct
FROM monthly_kpis
WHERE is_complete_month = 1
ORDER BY month;

-- 2. 成熟的首笔可观测购买同期群 90 天复购表现
SELECT
    cohort_month,
    cohort_size,
    repeat_90d_customers,
    ROUND(repeat_90d_rate * 100, 2) AS repeat_90d_rate_pct
FROM cohort_repeat
WHERE mature_90d = 1
ORDER BY cohort_month;

-- 3. RFM 人群的规模和历史价值结构
SELECT
    segment,
    customers,
    ROUND(customer_share * 100, 2) AS customer_share_pct,
    ROUND(gross_purchase_value, 2) AS gross_purchase_value,
    ROUND(net_value_share * 100, 2) AS net_value_share_pct,
    avg_recency_days,
    avg_frequency_orders
FROM rfm_segment_summary
ORDER BY gross_purchase_value DESC;

-- 4. 运营优先级与验收方式；这些是待验证方案，不是已发生效果
SELECT
    priority,
    segment,
    customers,
    ROUND(net_value_share * 100, 2) AS net_value_share_pct,
    proposed_action,
    validation_plan
FROM action_plan
ORDER BY priority;

-- 5. 国家市场的净收入结构，只描述历史贡献
SELECT
    country,
    ROUND(net_revenue, 2) AS net_revenue,
    sale_orders,
    customers
FROM country_summary
ORDER BY net_revenue DESC
LIMIT 10;
