SELECT
    risk_level,
    COUNT(*) AS total_contas,
    SUM(mrr) AS mrr_total,
    ROUND(SUM(mrr) * 100.0 / SUM(SUM(mrr)) OVER (), 1) AS pct_mrr
FROM gold.churn_score
GROUP BY risk_level
ORDER BY mrr_total DESC;