CREATE MATERIALIZED VIEW silver.crm_contracts AS

WITH cleaned AS (
    SELECT
        contract_id,
        account_id,
        INITCAP(TRIM(plan)) AS plan, -- primeira letra maiúscula e remove espaços em branco
        start_date,
        end_date,
        arr,
        INITCAP(TRIM(renewal_status)) AS renewal_status, -- primeira letra maiúscula e remove espaços em branco
        INITCAP(TRIM(payment_status)) AS payment_status, -- primeira letra maiúscula e remove espaços em branco
        auto_renew,
        TRIM(contract_owner) AS contract_owner, -- remove espaços em branco
        (end_date - CURRENT_DATE) AS days_until_expiry, -- calcula a diferença entre a data de término do contrato e a data atual
        ingested_at
    FROM bronze.crm_contracts
    WHERE contract_id IS NOT NULL
      AND start_date  IS NOT NULL
      AND end_date    IS NOT NULL
      AND end_date > start_date
)

SELECT
    contract_id,
    account_id,
    CASE WHEN LOWER(plan) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL -- se for vazio, n/a, na, null, none, -, --, undefined, (blank) então retorna NULL
    ELSE plan 
    END AS plan,
    start_date,
    end_date,
    arr,
    CASE WHEN LOWER(renewal_status) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL 
    ELSE renewal_status 
    END AS renewal_status,
    CASE WHEN LOWER(payment_status) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL 
    ELSE payment_status 
    END AS payment_status,
    auto_renew,
    CASE WHEN LOWER(contract_owner) IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)') THEN NULL 
    ELSE contract_owner 
    END AS contract_owner,
    days_until_expiry,
    ingested_at
FROM cleaned;