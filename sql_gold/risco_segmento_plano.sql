SELECT
    segment,
    plan,
    COUNT(*) AS total_contas,
    COUNT(*) FILTER (WHERE risk_level = 'Alto') AS alto,
    COUNT(*) FILTER (WHERE risk_level = 'Medio') AS medio,
    COUNT(*) FILTER (WHERE risk_level = 'Baixo') AS baixo,
    ROUND(
        COUNT(*) FILTER (WHERE risk_level = 'Alto') * 100.0
        / COUNT(*), 1
    ) AS pct_alto
FROM gold.churn_score
GROUP BY segment, plan
ORDER BY segment, pct_alto DESC;