SELECT
    -- média de cada sinal por nível de risco
    risk_level,
    COUNT(*) AS total_contas,
    ROUND(AVG(sinal_engajamento), 1) AS avg_sinal_engajamento,
    ROUND(AVG(sinal_suporte), 1) AS avg_sinal_suporte,
    ROUND(AVG(sinal_contrato), 1) AS avg_sinal_contrato,
    ROUND(AVG(sinal_crm), 1) AS avg_sinal_crm,
    ROUND(AVG(churn_score), 1) AS avg_churn_score,

    -- contribuição percentual de cada sinal no score médio
    ROUND(AVG(sinal_engajamento) * 100.0 / NULLIF(AVG(churn_score), 0), 1) AS pct_engajamento,
    ROUND(AVG(sinal_suporte) * 100.0 / NULLIF(AVG(churn_score), 0), 1) AS pct_suporte,
    ROUND(AVG(sinal_contrato) * 100.0 / NULLIF(AVG(churn_score), 0), 1) AS pct_contrato,
    ROUND(AVG(sinal_crm) * 100.0 / NULLIF(AVG(churn_score), 0), 1) AS pct_crm
FROM gold.churn_score
GROUP BY risk_level
ORDER BY avg_churn_score DESC;