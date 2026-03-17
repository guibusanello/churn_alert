CREATE TABLE crm_contracts (
    contract_id     TEXT PRIMARY KEY,          
    account_id      TEXT NOT NULL REFERENCES crm_accounts(account_id),
    plan            TEXT,
    start_date      DATE,
    end_date        DATE,
    arr             NUMERIC(10,2),
    renewal_status  TEXT,                      
    payment_status  TEXT,                      
    auto_renew      BOOLEAN,
    contract_owner  TEXT,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);