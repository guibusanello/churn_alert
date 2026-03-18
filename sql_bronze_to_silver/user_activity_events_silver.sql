CREATE MATERIALIZED VIEW silver.user_activity_events AS

WITH cleaned AS (
    SELECT
        e.event_id,
        a.account_id,
        e.org_id AS source_org_id,
        LOWER(TRIM(e.admin_email)) AS admin_email, -- email do usuário que gerou o evento
        TRIM(e.user_id) AS user_id,
        LOWER(TRIM(e.event_type)) AS event_type,
        e.event_date,
        e.event_time,
        e.session_id,
        LOWER(TRIM(e.platform)) AS platform,
        CASE WHEN LOWER(TRIM(e.feature_module)) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL -- padroniza os valores de feature_module
        ELSE INITCAP(TRIM(e.feature_module)) END AS feature_module,
        CASE
            WHEN e.duration_sec < 0 THEN NULL -- remove valores negativos de duração
            ELSE e.duration_sec
        END AS duration_sec,
        e.ingested_at,
        ROW_NUMBER() OVER ( -- deduplicação: elege o registro mais recente por combinação (org, user, event_type, data, hora) — mesma lógica de retry do SDK
        PARTITION BY e.org_id, e.user_id, e.event_type, e.event_date, e.event_time
        ORDER BY e.ingested_at DESC
        ) AS rn
    FROM bronze.user_activity_events e
    JOIN silver.crm_accounts a -- join com a tabela de contas do crm para obter o account_id
      ON SPLIT_PART(LOWER(TRIM(e.admin_email)), '@', 2) = a.email_domain
    WHERE e.event_id   IS NOT NULL
      AND e.org_id     IS NOT NULL
      AND e.event_date IS NOT NULL
      AND e.event_date <= CURRENT_DATE -- remove eventos futuros que indicam erro de coleta
      AND LOWER(TRIM(e.admin_email)) NOT IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)')
      AND e.admin_email LIKE '%@%'
)

SELECT
    event_id,
    account_id,
    source_org_id,
    admin_email,
    user_id,
    event_type,
    event_date,
    event_time,
    session_id,
    platform,
    feature_module,
    duration_sec,
    ingested_at
FROM cleaned
WHERE rn = 1;  -- mantém apenas uma ocorrência por evento duplicado