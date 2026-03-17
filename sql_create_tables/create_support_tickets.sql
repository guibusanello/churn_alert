CREATE TABLE support_tickets (
    ticket_id        TEXT PRIMARY KEY,         
    org_id           INT NOT NULL,             
    requester_email  TEXT NOT NULL,            
    subject          TEXT,
    category         TEXT,                    
    priority         TEXT,                     
    status           TEXT,                     
    created_date     DATE,
    resolved_date    DATE,                     
    resolution_days  INT,                      
    satisfaction     INT,                      
    assigned_agent   TEXT,
    reopened         BOOLEAN,
    ingested_at      TIMESTAMPTZ DEFAULT NOW()
);