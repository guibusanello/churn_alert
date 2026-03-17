CREATE TABLE user_activity_events (
    event_id        TEXT PRIMARY KEY,          
    org_id          TEXT NOT NULL,             
    admin_email     TEXT NOT NULL,            
    user_id         TEXT,
    event_type      TEXT,
    event_date      DATE,
    event_time      TIME,
    session_id      TEXT,
    platform        TEXT,                      
    feature_module  TEXT,
    duration_sec    INT,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);