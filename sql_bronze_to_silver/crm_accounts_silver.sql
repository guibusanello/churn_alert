CREATE MATERIALIZED VIEW silver.crm_accounts AS

WITH cleaned AS (
SELECT
  account_id,
  TRIM(company_name) AS company_name, -- remove espaços indesejados no começo e no fim do nome da empresa
  LOWER(TRIM(billing_email)) AS billing_email, -- remove espaços indesejados e deixa todos os caracteres em letra minúscula
  SPLIT_PART(LOWER(TRIM(billing_email)), '@', 2) AS email_domain, -- extrai o domínio do email, que será usado no join para unir os dados das outras tabelas
  INITCAP(TRIM(segment))   AS segment, -- coloca a primeira letra em maiúsculo e o restante em minúsculo
  INITCAP(TRIM(industry))  AS industry,
  INITCAP(TRIM(country))   AS country,
  INITCAP(TRIM(plan))      AS plan,
  INITCAP(TRIM(status))    AS status,
  employee_count,
  mrr,
  TRIM(cs_owner) AS cs_owner, -- remove espaços indesejados no início e no fim do texto
  created_date,
  last_qbr_date,
  ingested_at,
  CASE -- ajustar valores fora do intervalo entre 0 e 100 para não poluir o score final
        WHEN health_score < 0   THEN 0
        WHEN health_score > 100 THEN 100
        ELSE health_score
    END AS health_score,
  CASE -- ajuste de valores fora do intervalo entre 0 e 10 para não poluir o score final
        WHEN nps_score < 0 OR nps_score > 10 THEN NULL
        ELSE nps_score
    END AS nps_score
FROM bronze.crm_accounts
WHERE account_id IS NOT NULL AND billing_email LIKE '%@%')

-- select externo: converte valores '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)' em NULL
SELECT
    account_id,
    CASE WHEN LOWER(company_name) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE company_name
    END AS company_name,
    CASE WHEN LOWER(billing_email) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE billing_email 
    END AS billing_email,
    CASE WHEN LOWER(email_domain) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE email_domain 
    END AS email_domain,
    CASE WHEN LOWER(segment) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE segment 
    END AS segment,
    CASE WHEN LOWER(industry) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE industry 
    END AS industry,
    CASE WHEN LOWER(country) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE country 
    END AS country,
    CASE WHEN LOWER(plan) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE plan 
    END AS plan,
    CASE WHEN LOWER(status) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE status 
    END AS status,
    employee_count,
    mrr,
    CASE WHEN LOWER(cs_owner) IN (
        '', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)'
    ) THEN NULL 
    ELSE cs_owner 
    END AS cs_owner,
    created_date,
    last_qbr_date,
    ingested_at,
    health_score,
    nps_score
FROM cleaned
WHERE LOWER(billing_email) NOT IN ('', 'n/a', 'na', 'null', 'none', '-', '--', 'undefined', '(blank)');