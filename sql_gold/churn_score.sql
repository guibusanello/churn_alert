CREATE MATERIALIZED VIEW gold.churn_score AS

WITH active_accounts AS (
    SELECT
        account_id,
        company_name,
        segment,
        plan,
        mrr,
        status,
        cs_owner,
        health_score,
        nps_score
    FROM silver.crm_accounts
    WHERE status IN ('Active', 'At Risk')
),

-- SINAL 1: Engajamento — eventos últimos 30d vs 30d anterior (0–30 pts)
engagement AS (
    SELECT
        account_id,
        COUNT(*) FILTER (
            WHERE event_date >= CURRENT_DATE - INTERVAL '30 days') AS events_last_30d, -- Eventos nos últimos 30 dias
        COUNT(*) FILTER (
            WHERE event_date >= CURRENT_DATE - INTERVAL '60 days'
              AND event_date <  CURRENT_DATE - INTERVAL '30 days'
        ) AS events_prev_30d, -- Eventos nos 30 dias anteriores
        COUNT(DISTINCT user_id) FILTER (
            WHERE event_date >= CURRENT_DATE - INTERVAL '30 days'
        ) AS active_users_30d -- Usuários ativos nos últimos 30 dias
    FROM silver.user_activity_events
    GROUP BY account_id
),

engagement_scored AS ( -- Pontuação de engajamento
    SELECT
        account_id,
        events_last_30d,
        events_prev_30d,
        active_users_30d,
        CASE
            WHEN events_prev_30d = 0 AND events_last_30d = 0 THEN -100 -- Sem eventos nos últimos 60 dias
            WHEN events_prev_30d = 0 THEN 0 -- Sem eventos nos últimos 30 dias
            ELSE ROUND( -- Variação percentual de eventos
                (events_last_30d - events_prev_30d)::NUMERIC
                / events_prev_30d * 100, 1
            )
        END AS engagement_change_pct, -- Variação percentual de eventos
        CASE
            WHEN events_prev_30d = 0 AND events_last_30d = 0 THEN 30 -- Sem eventos nos últimos 60 dias
            WHEN events_last_30d = 0 THEN 30 -- Sem eventos nos últimos 30 dias
            WHEN events_prev_30d > 0 AND (events_last_30d::NUMERIC / events_prev_30d) < 0.5 THEN 25 -- Queda de mais de 50% nos eventos
            WHEN events_prev_30d > 0 AND (events_last_30d::NUMERIC / events_prev_30d) < 0.75 THEN 15 -- Queda de mais de 25% nos eventos
            ELSE 0 -- Queda de menos de 25% nos eventos
        END AS sinal_engajamento
    FROM engagement
),

-- SINAL 2: Suporte — tickets críticos abertos (0–25 pts)
support_scored AS (
    SELECT
        account_id,
        COUNT(*) FILTER ( -- Tickets críticos abertos
            WHERE priority IN ('Critical', 'High')
              AND status   IN ('Open', 'In Progress')
        ) AS open_critical_tickets,
        COUNT(*) FILTER ( -- Tickets reabertos
            WHERE reopened = TRUE
              AND created_date >= CURRENT_DATE - INTERVAL '30 days'
        ) AS reopened_tickets_30d,
        ROUND(AVG(satisfaction) FILTER (
            WHERE satisfaction IS NOT NULL -- CSAT nos últimos 90 dias
              AND created_date >= CURRENT_DATE - INTERVAL '90 days'
        ), 1) AS avg_csat_90d,
        CASE -- Pontuação de suporte
            WHEN COUNT(*) FILTER (
                WHERE priority IN ('Critical', 'High')
                  AND status   IN ('Open', 'In Progress')
            ) >= 3 THEN 25
            WHEN COUNT(*) FILTER (
                WHERE priority IN ('Critical', 'High')
                  AND status   IN ('Open', 'In Progress')
            ) >= 1 THEN 15
            ELSE 0
        END
        +
        CASE
            WHEN COUNT(*) FILTER ( -- Tickets reabertos
                WHERE reopened = TRUE
                  AND created_date >= CURRENT_DATE - INTERVAL '30 days'
            ) >= 2 THEN 5
            WHEN COUNT(*) FILTER (
                WHERE reopened = TRUE
                  AND created_date >= CURRENT_DATE - INTERVAL '30 days'
            ) >= 1 THEN 3
            ELSE 0
        END AS sinal_suporte
    FROM silver.support_tickets
    GROUP BY account_id
),

-- SINAL 3: Contrato — pagamento em atraso ou vencendo (0–25 pts)
contracts_scored AS (
    SELECT
        account_id,
        BOOL_OR(payment_status = 'Overdue') AS has_overdue, -- Pagamento em atraso
        BOOL_OR(
            days_until_expiry BETWEEN 0 AND 30
            AND renewal_status NOT IN ('Renewed')
        ) AS contract_expiring_soon, -- Contrato vencendo
        BOOL_OR(renewal_status = 'Not Renewed') AS has_not_renewed, -- Contrato não renovado
        CASE WHEN BOOL_OR(payment_status = 'Overdue') THEN 15 ELSE 0 END
        + CASE WHEN BOOL_OR(
            days_until_expiry BETWEEN 0 AND 30
            AND renewal_status NOT IN ('Renewed')
        ) THEN 10 ELSE 0 END
        + CASE WHEN BOOL_OR(renewal_status = 'Not Renewed') THEN 10 ELSE 0 END AS sinal_contrato -- Pontuação de contrato
    FROM silver.crm_contracts
    GROUP BY account_id
),

-- SINAL 4: Health score e NPS (0–20 pts)
crm_scored AS (
    SELECT
        account_id,
        health_score,
        nps_score,
        CASE
            WHEN health_score < 30 THEN 15 -- Health score baixo
            WHEN health_score < 50 THEN 10 -- Health score médio
            WHEN health_score < 70 THEN  5 -- Health score bom
            ELSE 0
        END
        +
        CASE
            WHEN nps_score IS NULL THEN  5 -- NPS não informado
            WHEN nps_score <= 3   THEN 10 -- NPS baixo
            WHEN nps_score <= 6   THEN  5 -- NPS médio
            ELSE 0
        END AS sinal_crm -- Pontuação de CRM
    FROM active_accounts
),

final_score AS (
    SELECT
        a.account_id,
        a.company_name,
        a.segment,
        a.plan,
        a.mrr,
        a.status AS crm_status,
        a.cs_owner,
        COALESCE(e.events_last_30d, 0) AS events_last_30d,
        COALESCE(e.events_prev_30d, 0) AS events_prev_30d,
        e.engagement_change_pct,
        COALESCE(e.active_users_30d, 0) AS active_users_30d,
        COALESCE(e.sinal_engajamento, 30) AS sinal_engajamento,  -- sem dados = risco máximo
        COALESCE(s.open_critical_tickets, 0) AS open_critical_tickets,
        COALESCE(s.reopened_tickets_30d, 0) AS reopened_tickets_30d,
        s.avg_csat_90d,
        COALESCE(s.sinal_suporte, 0) AS sinal_suporte,
        COALESCE(c.has_overdue, FALSE) AS has_overdue,
        COALESCE(c.contract_expiring_soon, FALSE) AS contract_expiring_soon,
        COALESCE(c.has_not_renewed, FALSE) AS has_not_renewed,
        COALESCE(c.sinal_contrato, 0) AS sinal_contrato,
        cs.health_score,
        cs.nps_score,
        cs.sinal_crm,
        LEAST(
            COALESCE(e.sinal_engajamento, 30)
            + COALESCE(s.sinal_suporte, 0)
            + COALESCE(c.sinal_contrato, 0)
            + cs.sinal_crm,
            100
        ) AS churn_score
    FROM active_accounts a
    LEFT JOIN engagement_scored e USING (account_id) 
    LEFT JOIN support_scored s USING (account_id)
    LEFT JOIN contracts_scored c USING (account_id)
    JOIN crm_scored cs USING (account_id)
)

SELECT
    RANK() OVER (ORDER BY churn_score DESC) AS risk_rank, -- rank de risco
    account_id,
    company_name,
    segment,
    plan,
    mrr,
    crm_status,
    cs_owner,
    CASE
        WHEN churn_score >= 60 THEN 'Alto'
        WHEN churn_score >= 35 THEN 'Medio'
        ELSE 'Baixo'
    END AS risk_level,
    churn_score,
    sinal_engajamento,
    sinal_suporte,
    sinal_contrato,
    sinal_crm,
    events_last_30d,
    engagement_change_pct,
    active_users_30d,
    open_critical_tickets,
    avg_csat_90d,
    has_overdue,
    contract_expiring_soon,
    health_score,
    nps_score,
    NOW() AS scored_at -- data de execução do script
FROM final_score
ORDER BY churn_score DESC, mrr DESC;