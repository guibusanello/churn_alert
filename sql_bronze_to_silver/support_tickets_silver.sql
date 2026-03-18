CREATE MATERIALIZED VIEW silver.support_tickets AS

WITH cleaned AS (
    SELECT
        t.ticket_id,
        a.account_id,
        t.org_id AS source_org_id,
        LOWER(TRIM(t.requester_email)) AS requester_email,
        CASE WHEN LOWER(TRIM(t.subject)) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL -- padroniza valores nulos
        ELSE TRIM(t.subject) END AS subject,
        CASE WHEN LOWER(TRIM(t.category)) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL
        ELSE INITCAP(TRIM(t.category)) END AS category,
        CASE WHEN LOWER(TRIM(t.priority)) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL
        ELSE INITCAP(TRIM(t.priority)) END AS priority,
        CASE WHEN LOWER(TRIM(t.status)) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL
        ELSE INITCAP(TRIM(t.status)) END AS status,
        t.created_date,
        t.resolved_date,
        CASE
            WHEN t.resolution_days < 0 THEN NULL
            ELSE t.resolution_days
        END AS resolution_days,
        CASE
            WHEN t.satisfaction < 1 OR t.satisfaction > 5 THEN NULL
            ELSE t.satisfaction
        END AS satisfaction,
        CASE WHEN LOWER(TRIM(t.assigned_agent)) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL
        ELSE TRIM(t.assigned_agent) END AS assigned_agent,
        t.reopened,
        t.ingested_at,
        ROW_NUMBER() OVER ( -- deduplicação: mesmo ticket pode chegar mais de uma vez via webhook duplicado ou re-export do Zendesk/Intercom
        PARTITION BY t.ticket_id, t.org_id -- critério: ticket_id + org_id identificam unicamente o ticket
        ORDER BY t.ingested_at DESC -- em caso de duplicata, mantém o registro mais recente
        ) AS rn
    FROM bronze.support_tickets t
    JOIN silver.crm_accounts a -- junta com a tabela de contas do crm para obter o account_id
      ON SPLIT_PART(LOWER(TRIM(t.requester_email)), '@', 2) = a.email_domain
    WHERE t.ticket_id IS NOT NULL
      AND LOWER(TRIM(t.requester_email)) NOT IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)')
      AND t.requester_email LIKE '%@%'
)

SELECT
    ticket_id,
    account_id,
    source_org_id,
    requester_email,
    subject,
    category,
    priority,
    status,
    created_date,
    resolved_date,
    resolution_days,
    satisfaction,
    assigned_agent,
    reopened,
    ingested_at
FROM cleaned
WHERE rn = 1;