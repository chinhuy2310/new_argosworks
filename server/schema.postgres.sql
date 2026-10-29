-- ==============================================================================
-- ARGOS WORKS — Canonical Schema for PostgreSQL (Production)
-- 100% synchronized with SQLite schema.sql for seamless dual-engine operation.
-- ==============================================================================

-- 1. Departments / Organizations
CREATE TABLE IF NOT EXISTS departments (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    color_index INTEGER NOT NULL DEFAULT 1,
    local_prefix VARCHAR(64) NOT NULL DEFAULT '',
    jira_key VARCHAR(64) NOT NULL DEFAULT '',
    custom_categories TEXT NOT NULL DEFAULT ''
);

-- 2. Card sequence counter per department
CREATE TABLE IF NOT EXISTS card_sequences (
    dept_id VARCHAR(64) PRIMARY KEY REFERENCES departments(id) ON DELETE CASCADE,
    last_seq INTEGER NOT NULL DEFAULT 0
);

-- 3. Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(128) NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    dept_id VARCHAR(64) NOT NULL REFERENCES departments(id),
    email TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    salt VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    -- Password metadata: required by services/auth.py create_user()/verify_password()
    -- for auto-upgrading legacy PBKDF2 hashes. Missing here previously made user
    -- creation (setup wizard / admin create / register) fail on PostgreSQL.
    hash_algo VARCHAR(32) NOT NULL DEFAULT 'pbkdf2_sha256',
    iterations INTEGER NOT NULL DEFAULT 600000,
    role VARCHAR(32) NOT NULL DEFAULT 'member', -- admin, manager, member, viewer
    is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS'),
    CONSTRAINT uq_user_name_dept UNIQUE(name, dept_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique ON users(username) WHERE username != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users(LOWER(username)) WHERE username != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users(LOWER(email)) WHERE email != '';

-- 4. Records (Work handover / Tasks)
CREATE TABLE IF NOT EXISTS records (
    id BIGINT PRIMARY KEY,  -- timestamp ms, NOT autoincrement
    dept_id VARCHAR(64) NOT NULL REFERENCES departments(id),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '프로젝트 미지정',
    assignee_id INTEGER REFERENCES users(id),
    assignee_name TEXT NOT NULL,
    assignee_email TEXT NOT NULL DEFAULT '',
    start_date VARCHAR(64) NOT NULL DEFAULT '',
    due_date VARCHAR(64) NOT NULL DEFAULT '',
    work_date VARCHAR(64) NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    memo TEXT NOT NULL DEFAULT '',
    status VARCHAR(64) NOT NULL DEFAULT '진행',
    priority VARCHAR(64) NOT NULL DEFAULT '보통',
    card_code VARCHAR(64) NOT NULL DEFAULT '',
    participants TEXT NOT NULL DEFAULT '',
    parent_key VARCHAR(64) NOT NULL DEFAULT '',
    is_scheduled INTEGER NOT NULL DEFAULT 1,
    is_private INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS'),
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_records_dept ON records(dept_id);
CREATE INDEX IF NOT EXISTS idx_records_assignee ON records(assignee_name);
CREATE INDEX IF NOT EXISTS idx_records_date ON records(work_date);
CREATE INDEX IF NOT EXISTS idx_records_assignee_email ON records(assignee_email);
CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_card_code ON records(card_code);

-- 5. Record Attachments
CREATE TABLE IF NOT EXISTS record_attachments (
    id SERIAL PRIMARY KEY,
    record_id BIGINT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    uploaded_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_record_attachments_record ON record_attachments(record_id);

-- 6. Record Comments
CREATE TABLE IF NOT EXISTS record_comments (
    id SERIAL PRIMARY KEY,
    record_id BIGINT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    author_name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_record_comments_record ON record_comments(record_id);

-- 7. Record Jira mapping
CREATE TABLE IF NOT EXISTS record_jira (
    record_id BIGINT PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
    jira_key VARCHAR(64) NOT NULL,
    jira_status VARCHAR(64) DEFAULT '',
    jira_url TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_record_jira_key ON record_jira(jira_key);

-- 8. Schedule Events (Calendar)
CREATE TABLE IF NOT EXISTS schedule_events (
    id BIGINT PRIMARY KEY,  -- timestamp ms
    owner_id INTEGER REFERENCES users(id),
    owner_name TEXT NOT NULL,
    owner_dept_id VARCHAR(64) NOT NULL,
    owner_email TEXT NOT NULL DEFAULT '',
    type VARCHAR(64) NOT NULL,
    title TEXT NOT NULL,
    start_date VARCHAR(64) NOT NULL,
    end_date VARCHAR(64) NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    approval_status VARCHAR(32) NOT NULL DEFAULT 'approved', -- 'pending' | 'approved' | 'rejected'
    approved_by TEXT DEFAULT '',
    approved_at VARCHAR(64) DEFAULT '',
    reject_reason TEXT DEFAULT '',
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_schedule_owner ON schedule_events(owner_id);
CREATE INDEX IF NOT EXISTS idx_schedule_dates ON schedule_events(start_date, end_date);

-- 9. Schedule Participants
CREATE TABLE IF NOT EXISTS schedule_participants (
    id SERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES schedule_events(id) ON DELETE CASCADE,
    user_name TEXT NOT NULL,
    user_dept_id VARCHAR(64) NOT NULL,
    user_email TEXT NOT NULL DEFAULT '',
    is_owner INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_schedule_participants_event ON schedule_participants(event_id);

-- 10. Products (PIM)
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(64) PRIMARY KEY,
    model VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    family VARCHAR(128) NOT NULL DEFAULT '',
    lifecycle VARCHAR(64) NOT NULL DEFAULT '판매 중',
    category VARCHAR(128) NOT NULL DEFAULT '일반',
    summary TEXT NOT NULL DEFAULT '',
    memo TEXT NOT NULL DEFAULT '',
    specs TEXT NOT NULL DEFAULT '{}',
    procurement TEXT,
    price BIGINT DEFAULT 0,
    currency VARCHAR(16) NOT NULL DEFAULT 'KRW',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'internal'
);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source);
CREATE INDEX IF NOT EXISTS idx_products_model ON products(model);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);

-- 11. Product Attachments
CREATE TABLE IF NOT EXISTS product_attachments (
    id SERIAL PRIMARY KEY,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    uploaded_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_product_attachments_prod ON product_attachments(product_id);

-- 12. Product Categories
CREATE TABLE IF NOT EXISTS product_categories (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    spec_template TEXT NOT NULL DEFAULT '[]',
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);

-- 13. Chat Sessions & Messages (AI Agent)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id VARCHAR(64) PRIMARY KEY,
    user_name VARCHAR(128) NOT NULL,
    user_dept_id VARCHAR(64) NOT NULL,
    title VARCHAR(512) NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_name, user_dept_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGINT PRIMARY KEY,  -- timestamp ms
    session_id VARCHAR(64) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL,
    metadata TEXT,
    created_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);

-- 14. System Activities
CREATE TABLE IF NOT EXISTS activities (
    id VARCHAR(128) PRIMARY KEY,
    issue_key VARCHAR(64) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    action_detail TEXT NOT NULL DEFAULT '',
    author_name VARCHAR(128) NOT NULL,
    author_email VARCHAR(255) NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    status VARCHAR(64) NOT NULL DEFAULT '',
    priority VARCHAR(64) NOT NULL DEFAULT '보통',
    issue_type VARCHAR(64) NOT NULL DEFAULT '',
    assignee_name VARCHAR(128) NOT NULL DEFAULT '',
    assignee_dept VARCHAR(128) NOT NULL DEFAULT '',
    source VARCHAR(64) NOT NULL DEFAULT 'jarvis',
    created_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_created ON activities(created_at);
CREATE INDEX IF NOT EXISTS idx_activities_issue ON activities(issue_key);

-- 15. Lounge Messages (Internal Team Chat)
CREATE TABLE IF NOT EXISTS lounge_messages (
    id BIGINT PRIMARY KEY,  -- timestamp ms
    conversation_key VARCHAR(128) NOT NULL,
    from_name VARCHAR(128) NOT NULL,
    from_dept_id VARCHAR(64) NOT NULL,
    to_name VARCHAR(128) NOT NULL,
    to_dept_id VARCHAR(64) NOT NULL,
    text TEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lounge_conversation ON lounge_messages(conversation_key);

-- 16. Sessions (Auth)
CREATE TABLE IF NOT EXISTS sessions (
    token VARCHAR(255) PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    user_name VARCHAR(128) NOT NULL,
    user_dept_id VARCHAR(64) NOT NULL,
    user_email VARCHAR(255) NOT NULL DEFAULT '',
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL,
    last_active_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);

-- 17. Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(128) PRIMARY KEY,
    recipient_email VARCHAR(255) NOT NULL DEFAULT '',
    recipient_name TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '시스템',
    type VARCHAR(64) NOT NULL DEFAULT 'assign',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    link_id VARCHAR(128) DEFAULT '',
    tag VARCHAR(64) DEFAULT '',
    tag_type VARCHAR(64) DEFAULT 'info',
    is_read INTEGER NOT NULL DEFAULT 0,
    read_at VARCHAR(64),
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_email, is_read, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_name ON notifications(recipient_name, is_read, created_at);

-- 18. Jira Sync Metadata
CREATE TABLE IF NOT EXISTS sync_meta (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);

-- 19. Jira Persistence Tables
CREATE TABLE IF NOT EXISTS jira_issues (
    jira_key VARCHAR(64) PRIMARY KEY,
    jira_id VARCHAR(64) DEFAULT '',
    project_key VARCHAR(64) DEFAULT '',
    project_name VARCHAR(255) DEFAULT '',
    issue_type VARCHAR(64) DEFAULT '',
    is_subtask INTEGER DEFAULT 0,
    parent_key VARCHAR(64) DEFAULT '',
    parent_summary TEXT DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    status VARCHAR(64) DEFAULT '',
    status_name VARCHAR(64) DEFAULT '',
    priority VARCHAR(64) DEFAULT 'Medium',
    assignee_name TEXT DEFAULT '',
    assignee_account_id VARCHAR(128) DEFAULT '',
    assignee_avatar TEXT DEFAULT '',
    reporter_name TEXT DEFAULT '',
    dept_id VARCHAR(64) DEFAULT '',
    start_date VARCHAR(64) DEFAULT '',
    due_date VARCHAR(64) DEFAULT '',
    resolution_date VARCHAR(64) DEFAULT '',
    created_at VARCHAR(64) DEFAULT '',
    updated_at VARCHAR(64) DEFAULT '',
    tags TEXT DEFAULT '[]',
    raw_json TEXT DEFAULT '',
    synced_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_jira_assignee ON jira_issues(assignee_name);
CREATE INDEX IF NOT EXISTS idx_jira_dates ON jira_issues(start_date, due_date, updated_at);
CREATE INDEX IF NOT EXISTS idx_jira_parent ON jira_issues(parent_key);
CREATE INDEX IF NOT EXISTS idx_jira_dept ON jira_issues(dept_id);

CREATE TABLE IF NOT EXISTS jira_comments (
    comment_id VARCHAR(128) PRIMARY KEY,
    jira_key VARCHAR(64) NOT NULL REFERENCES jira_issues(jira_key) ON DELETE CASCADE,
    author_name VARCHAR(128) DEFAULT '',
    author_account_id VARCHAR(128) DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_at VARCHAR(64) DEFAULT '',
    updated_at VARCHAR(64) DEFAULT '',
    source VARCHAR(32) DEFAULT 'jira'
);
CREATE INDEX IF NOT EXISTS idx_jira_comments_key ON jira_comments(jira_key);
CREATE INDEX IF NOT EXISTS idx_jira_comments_author ON jira_comments(author_name);

CREATE TABLE IF NOT EXISTS jira_attachments (
    attachment_id VARCHAR(128) PRIMARY KEY,
    jira_key VARCHAR(64) NOT NULL REFERENCES jira_issues(jira_key) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size BIGINT DEFAULT 0,
    mime_type VARCHAR(128) DEFAULT '',
    jira_url TEXT DEFAULT '',
    local_path TEXT DEFAULT '',
    created_at VARCHAR(64) DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jira_attach_key ON jira_attachments(jira_key);

CREATE TABLE IF NOT EXISTS jira_changelog (
    id VARCHAR(128) PRIMARY KEY,
    issue_key VARCHAR(64) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    action_detail TEXT NOT NULL DEFAULT '',
    author_name VARCHAR(128) NOT NULL DEFAULT '',
    author_avatar TEXT DEFAULT '',
    created_at VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status VARCHAR(64) NOT NULL DEFAULT '',
    priority VARCHAR(64) NOT NULL DEFAULT '보통',
    issue_type VARCHAR(64) NOT NULL DEFAULT '',
    assignee_name VARCHAR(128) NOT NULL DEFAULT '',
    assignee_dept VARCHAR(128) NOT NULL DEFAULT '',
    source VARCHAR(32) NOT NULL DEFAULT 'jira'
);
CREATE INDEX IF NOT EXISTS idx_jira_changelog_date ON jira_changelog(created_at);
CREATE INDEX IF NOT EXISTS idx_jira_changelog_key ON jira_changelog(issue_key);

-- 20. Schema Migrations Engine
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    applied_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);

-- 21. Enterprise Audit Log Engine
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    timestamp VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS'),
    user_id INTEGER,
    username TEXT NOT NULL DEFAULT '',
    dept_id VARCHAR(64) NOT NULL DEFAULT '',
    ip VARCHAR(64) NOT NULL DEFAULT '',
    action VARCHAR(64) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

-- 22. Enterprise License & Capacity Management
CREATE TABLE IF NOT EXISTS license_info (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    customer_name VARCHAR(255) NOT NULL DEFAULT 'Argos Enterprise Trial',
    license_key VARCHAR(512) NOT NULL DEFAULT '',
    max_seats INTEGER NOT NULL DEFAULT 25,
    expiry_date VARCHAR(64) NOT NULL DEFAULT '2099-12-31',
    modules_json TEXT NOT NULL DEFAULT '["canvas","rag","jira","pim","schedule","audit"]',
    is_active INTEGER NOT NULL DEFAULT 1,
    activated_at VARCHAR(64) NOT NULL DEFAULT '',
    last_seen_ts DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);


-- 23. AI Usage & Token Tracking
CREATE TABLE IF NOT EXISTS ai_usage (
    id SERIAL PRIMARY KEY,
    user_name VARCHAR(128) NOT NULL,
    dept_id VARCHAR(64) NOT NULL DEFAULT '',
    provider VARCHAR(64) NOT NULL,          -- gemini, openai, claude, ollama
    model VARCHAR(128) NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    session_id VARCHAR(128) DEFAULT '',
    feature VARCHAR(64) NOT NULL DEFAULT 'chat',  -- chat, ask, auto_classify
    created_at VARCHAR(64) NOT NULL DEFAULT TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage(user_name, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_dept ON ai_usage(dept_id, created_at);

-- 21. Login Attempts (persistent brute-force lockout)
-- Must match schema.sql: without this table PostgreSQL silently degrades the
-- account/IP lockout to an in-memory fallback (see services/auth.py).
CREATE TABLE IF NOT EXISTS login_attempts (
    id BIGSERIAL PRIMARY KEY,
    ip VARCHAR(64) NOT NULL,
    identifier VARCHAR(255) NOT NULL,
    failed_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_ident ON login_attempts(ip, identifier, failed_at);

CREATE TABLE IF NOT EXISTS id_allocator (
    name VARCHAR(64) PRIMARY KEY,
    last_value BIGINT NOT NULL
);

-- Baseline Department & License Seeds for PostgreSQL (Korean Native B2B)
-- The signed trial licence below counts 60 days from the FIRST activation
-- (license_info.activated_at) and has no absolute end date.
INSERT INTO departments (id, name, color_index, local_prefix, jira_key, custom_categories) VALUES
('mgmt', '경영지원·기획실', 1, 'MGMT', 'MGMT', '["경영전략","예산승인","주간보고","대외협력"]'),
('dev', '소프트웨어·AI개발팀', 2, 'DEV', 'ARGOS', '["인프라","기능개발","보안강화","성능최적화","API연동"]'),
('sales', 'B2B사업·고객지원팀', 3, 'SALES', 'SALES', '["계약체결","고객사미팅","입찰제안","기술지원"]'),
('hr', '인사총무·운영관리팀', 4, 'HR', 'HR', '["채용","직무교육","사내복지","인프라지원"]'),
('hq', '품질관리·감사준법팀', 5, 'HQ', 'HQ', '["내부감사","보안점검","SLA검증","인증심사"]')
ON CONFLICT (id) DO NOTHING;

INSERT INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active)
VALUES (1, 'Argos Enterprise Trial', 'AGY-eyJjdXN0b21lciI6IkFyZ29zIEVudGVycHJpc2UgVHJpYWwiLCJpYXQiOiIyMDI2LTEwLTI5IiwibW9kdWxlcyI6WyJjYW52YXMiLCJwaW0iLCJqaXJhIiwicmFnIiwic2NoZWR1bGUiLCJhdWRpdCJdLCJzZWF0cyI6NTAsInRlcm1fZGF5cyI6NjAsInRyaWFsIjp0cnVlfQ.ovSRoVxez65COM4zzyVnNKrZ5chxofIqcyVtCWYq-ExX5KLt6vb8JrBHDPW21ygMCTAKXm63sMLVmVWZ6jtQDQ', 50, '', '["canvas","pim","jira","rag","schedule","audit"]', 1)
ON CONFLICT (id) DO NOTHING;

