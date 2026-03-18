SELECT
    risk_rank,
    company_name,
    cs_owner,
    plan,
    mrr,
    risk_level,
    churn_score,
    sinal_engajamento,
    sinal_suporte,
    sinal_contrato,
    sinal_crm
FROM gold.churn_score
WHERE risk_level = 'Alto'
ORDER BY risk_rank;