-- Enable foreign keys (also done in Python)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS departments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color_index INTEGER NOT NULL DEFAULT 1,
    local_prefix TEXT NOT NULL DEFAULT '',
    jira_key TEXT NOT NULL DEFAULT '',
    custom_categories TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS card_sequences (
    dept_id TEXT PRIMARY KEY REFERENCES departments(id) ON DELETE CASCADE,
    last_seq INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    dept_id TEXT NOT NULL REFERENCES departments(id),
    email TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    hash_algo TEXT NOT NULL DEFAULT 'pbkdf2_sha256',
    iterations INTEGER NOT NULL DEFAULT 600000,
    is_admin INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'member',
    disabled INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    UNIQUE(name, dept_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique ON users(username) WHERE username != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email != '';

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,  -- timestamp ms, NOT autoincrement
    dept_id TEXT NOT NULL REFERENCES departments(id),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '프로젝트 미지정',
    assignee_id INTEGER REFERENCES users(id),
    assignee_name TEXT NOT NULL,
    assignee_email TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    due_date TEXT NOT NULL DEFAULT '',
    work_date TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',  -- JSON array
    memo TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '진행',
    priority TEXT NOT NULL DEFAULT '보통',
    card_code TEXT NOT NULL DEFAULT '',
    participants TEXT NOT NULL DEFAULT '',
    parent_key TEXT NOT NULL DEFAULT '',
    is_scheduled INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    is_private INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS record_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS record_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    author_name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS record_jira (
    record_id INTEGER PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
    jira_key TEXT NOT NULL,
    jira_status TEXT DEFAULT '',
    jira_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schedule_events (
    id INTEGER PRIMARY KEY,  -- timestamp ms
    owner_id INTEGER REFERENCES users(id),
    owner_name TEXT NOT NULL,
    owner_dept_id TEXT NOT NULL,
    owner_email TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    approval_status TEXT NOT NULL DEFAULT 'approved', -- 'pending' | 'approved' | 'rejected'
    approved_by TEXT DEFAULT '',
    approved_at TEXT DEFAULT '',
    reject_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS schedule_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES schedule_events(id) ON DELETE CASCADE,
    user_name TEXT NOT NULL,
    user_dept_id TEXT NOT NULL,
    user_email TEXT NOT NULL DEFAULT '',
    is_owner INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    display_name TEXT NOT NULL,
    family TEXT NOT NULL DEFAULT '',
    lifecycle TEXT NOT NULL DEFAULT '판매 중',
    category TEXT NOT NULL DEFAULT '일반',
    summary TEXT NOT NULL DEFAULT '',
    memo TEXT NOT NULL DEFAULT '',
    specs TEXT NOT NULL DEFAULT '{}',   -- JSON object
    procurement TEXT,                    -- JSON object, nullable
    price INTEGER DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'KRW',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'internal'
);

CREATE TABLE IF NOT EXISTS product_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS product_categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    spec_template TEXT NOT NULL DEFAULT '[]', -- JSON array of field definitions
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    user_name TEXT NOT NULL,
    user_dept_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,  -- timestamp ms
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL,
    metadata TEXT,  -- JSON, nullable
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    issue_key TEXT NOT NULL,
    action_type TEXT NOT NULL,
    action_detail TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL,
    author_email TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT '보통',
    issue_type TEXT NOT NULL DEFAULT '',
    assignee_name TEXT NOT NULL DEFAULT '',
    assignee_dept TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'jarvis',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lounge_messages (
    id INTEGER PRIMARY KEY,  -- timestamp ms
    conversation_key TEXT NOT NULL,
    from_name TEXT NOT NULL,
    from_dept_id TEXT NOT NULL,
    to_name TEXT NOT NULL,
    to_dept_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    user_name TEXT NOT NULL,
    user_dept_id TEXT NOT NULL,
    user_email TEXT NOT NULL DEFAULT '',
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,  -- Unix epoch seconds
    last_active_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    recipient_email TEXT NOT NULL DEFAULT '',
    recipient_name TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '시스템',
    type TEXT NOT NULL DEFAULT 'assign',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    link_id TEXT DEFAULT '',
    tag TEXT DEFAULT '',
    tag_type TEXT DEFAULT 'info',
    is_read INTEGER NOT NULL DEFAULT 0,
    read_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_records_dept ON records(dept_id);
CREATE INDEX IF NOT EXISTS idx_records_assignee ON records(assignee_name);
CREATE INDEX IF NOT EXISTS idx_records_date ON records(work_date);
CREATE INDEX IF NOT EXISTS idx_records_assignee_email ON records(assignee_email);
CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_card_code ON records(card_code);
CREATE INDEX IF NOT EXISTS idx_record_attachments_record ON record_attachments(record_id);
CREATE INDEX IF NOT EXISTS idx_record_comments_record ON record_comments(record_id);
CREATE INDEX IF NOT EXISTS idx_record_jira_key ON record_jira(jira_key);
CREATE INDEX IF NOT EXISTS idx_schedule_owner ON schedule_events(owner_id);
CREATE INDEX IF NOT EXISTS idx_schedule_dates ON schedule_events(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_schedule_participants_event ON schedule_participants(event_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_name, user_dept_id);
CREATE INDEX IF NOT EXISTS idx_lounge_conversation ON lounge_messages(conversation_key);
CREATE INDEX IF NOT EXISTS idx_activities_created ON activities(created_at);
CREATE INDEX IF NOT EXISTS idx_activities_issue ON activities(issue_key);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_email, is_read, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_name ON notifications(recipient_name, is_read, created_at);

-- Jira Persistence Tables
CREATE TABLE IF NOT EXISTS sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS jira_issues (
    jira_key TEXT PRIMARY KEY,
    jira_id TEXT DEFAULT '',
    project_key TEXT DEFAULT '',
    project_name TEXT DEFAULT '',
    issue_type TEXT DEFAULT '',
    is_subtask INTEGER DEFAULT 0,
    parent_key TEXT DEFAULT '',
    parent_summary TEXT DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    status TEXT DEFAULT '',
    status_name TEXT DEFAULT '',
    priority TEXT DEFAULT 'Medium',
    assignee_name TEXT DEFAULT '',
    assignee_account_id TEXT DEFAULT '',
    assignee_avatar TEXT DEFAULT '',
    reporter_name TEXT DEFAULT '',
    dept_id TEXT DEFAULT '',
    start_date TEXT DEFAULT '',
    due_date TEXT DEFAULT '',
    resolution_date TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    raw_json TEXT DEFAULT '',
    synced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS jira_comments (
    comment_id TEXT PRIMARY KEY,
    jira_key TEXT NOT NULL REFERENCES jira_issues(jira_key) ON DELETE CASCADE,
    author_name TEXT DEFAULT '',
    author_account_id TEXT DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    source TEXT DEFAULT 'jira'
);

CREATE TABLE IF NOT EXISTS jira_attachments (
    attachment_id TEXT PRIMARY KEY,
    jira_key TEXT NOT NULL REFERENCES jira_issues(jira_key) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    mime_type TEXT DEFAULT '',
    jira_url TEXT DEFAULT '',
    local_path TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS jira_changelog (
    id TEXT PRIMARY KEY,
    issue_key TEXT NOT NULL,
    action_type TEXT NOT NULL,
    action_detail TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    author_avatar TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT '보통',
    issue_type TEXT NOT NULL DEFAULT '',
    assignee_name TEXT NOT NULL DEFAULT '',
    assignee_dept TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'jira'
);

CREATE INDEX IF NOT EXISTS idx_jira_assignee ON jira_issues(assignee_name);
CREATE INDEX IF NOT EXISTS idx_jira_dates ON jira_issues(start_date, due_date, updated_at);
CREATE INDEX IF NOT EXISTS idx_jira_parent ON jira_issues(parent_key);
CREATE INDEX IF NOT EXISTS idx_jira_dept ON jira_issues(dept_id);
CREATE INDEX IF NOT EXISTS idx_jira_comments_key ON jira_comments(jira_key);
CREATE INDEX IF NOT EXISTS idx_jira_comments_author ON jira_comments(author_name);
CREATE INDEX IF NOT EXISTS idx_jira_attach_key ON jira_attachments(jira_key);
CREATE INDEX IF NOT EXISTS idx_jira_changelog_date ON jira_changelog(created_at);
CREATE INDEX IF NOT EXISTS idx_jira_changelog_key ON jira_changelog(issue_key);

-- Schema Migrations Engine
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

-- Enterprise Audit Log Engine (Immutable Audit Trail)
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    user_id INTEGER,
    username TEXT NOT NULL DEFAULT '',
    dept_id TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,       -- LOGIN, LOGOUT, RECORD_VIEW, RECORD_CREATE, RECORD_UPDATE, RECORD_DELETE, PIM_PRICE_UPDATE, BACKUP_CREATE, BACKUP_RESTORE, SETTINGS_CHANGE, USER_ROLE_CHANGE
    target_type TEXT NOT NULL,  -- record, product, user, backup, settings, session
    target_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

-- Enterprise License & Capacity Management
CREATE TABLE IF NOT EXISTS license_info (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    customer_name TEXT NOT NULL DEFAULT 'Argos Enterprise Trial',
    license_key TEXT NOT NULL DEFAULT '',
    max_seats INTEGER NOT NULL DEFAULT 25,
    expiry_date TEXT NOT NULL DEFAULT '2099-12-31',
    modules_json TEXT NOT NULL DEFAULT '["canvas","rag","jira","pim","schedule","audit"]',
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

-- AI Usage Tracking Engine (Cost & Token Monitoring)
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    dept_id TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,          -- gemini, openai, claude, ollama
    model TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    session_id TEXT DEFAULT '',
    feature TEXT NOT NULL DEFAULT 'chat',  -- chat, ask, auto_classify
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage(user_name, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_dept ON ai_usage(dept_id, created_at);

CREATE TABLE IF NOT EXISTS product_categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    spec_template TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    identifier TEXT NOT NULL,
    failed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_ident ON login_attempts(ip, identifier, failed_at);

-- Baseline Department & License Seeds for Clean Environments (Korean Native B2B)
-- NOTE: The license below is a signed 50-seat EVALUATION license (expires 2027-12-31).
-- Production deployments must activate a commercial key issued by the vendor
-- (tools/vendor/license_tool.py). Unsigned/tampered keys are rejected at runtime.
INSERT OR IGNORE INTO departments (id, name, color_index, local_prefix, jira_key, custom_categories) VALUES
('mgmt', '경영지원·기획실', 1, 'MGMT', 'MGMT', '["경영전략","예산승인","주간보고","대외협력"]'),
('dev', '소프트웨어·AI개발팀', 2, 'DEV', 'ARGOS', '["인프라","기능개발","보안강화","성능최적화","API연동"]'),
('sales', 'B2B사업·고객지원팀', 3, 'SALES', 'SALES', '["계약체결","고객사미팅","입찰제안","기술지원"]'),
('hr', '인사총무·운영관리팀', 4, 'HR', 'HR', '["채용","직무교육","사내복지","인프라지원"]'),
('hq', '품질관리·감사준법팀', 5, 'HQ', 'HQ', '["내부감사","보안점검","SLA검증","인증심사"]');

INSERT OR IGNORE INTO license_info (id, customer_name, license_key, max_seats, expiry_date, modules_json, is_active)
VALUES (1, 'Argos Enterprise Trial', 'AGY-eyJjdXN0b21lciI6IkFyZ29zIEVudGVycHJpc2UgVHJpYWwiLCJleHBpcnkiOiIyMDI3LTEyLTMxIiwiaWF0IjoiMjAyNi0xMC0yMyIsIm1vZHVsZXMiOlsiY2FudmFzIiwicGltIiwiamlyYSIsInJhZyIsInNjaGVkdWxlIiwiYXVkaXQiXSwic2VhdHMiOjUwfQ.yEYIb5-mi0VGep5q-vMMi_EHjG8xb2Frsamytfw_sUKjQFFizBci55Q-0bh8sdoq9NOAorGqC_xbmtp5LlDMDw', 50, '2027-12-31', '["canvas","pim","jira","rag","schedule","audit"]', 1);

