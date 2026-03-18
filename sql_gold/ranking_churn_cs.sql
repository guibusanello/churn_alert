SELECT
    cs_owner,
    COUNT(*) AS total_carteira,
    COUNT(*) FILTER (WHERE risk_level = 'Alto') AS contas_alto,
    COUNT(*) FILTER (WHERE risk_level = 'Medio') AS contas_medio,
    COUNT(*) FILTER (WHERE risk_level = 'Baixo') AS contas_baixo,
    SUM(mrr) FILTER (WHERE risk_level = 'Alto') AS mrr_em_risco,
    ROUND(COUNT(*) FILTER (WHERE risk_level = 'Alto') * 100.0 / COUNT(*), 1) AS pct_carteira_em_risco
FROM gold.churn_score
GROUP BY cs_owner
ORDER BY mrr_em_risco DESC;