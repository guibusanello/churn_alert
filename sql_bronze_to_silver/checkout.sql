-- Conta registros em cada tabela silver para verificar se a migração foi concluída

SELECT
    'crm_accounts' AS tabela, COUNT(*) AS registros FROM silver.crm_accounts
UNION ALL
SELECT
    'crm_contracts' AS tabela, COUNT(*) FROM silver.crm_contracts
UNION ALL
SELECT
    'user_activity_events' AS tabela, COUNT(*) FROM silver.user_activity_events
UNION ALL
SELECT
    'support_tickets' AS tabela, COUNT(*) FROM silver.support_tickets;