CREATE TABLE crm_accounts (
  account_id TEXT PRIMARY KEY,
  company_name TEXT NOT NULL,
  billing_email TEXT NOT NULL,
  segment TEXT,
  industry TEXT,
  country TEXT,
  employee_count TEXT,
  plan TEXT,
  mrr NUMERIC(10,2),
  status TEXT,
  cs_owner TEXT,
  created_date DATE,
  health_score INT,
  nps_score INT,
  last_qbr_date DATE,
  ingested_at TIMESTAMPTZ DEFAULT NOW()
);