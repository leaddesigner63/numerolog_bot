PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id TEXT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_tariff_selected INTEGER,
    is_bought INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    birth_date TEXT NOT NULL,
    birth_time TEXT,
    birth_name TEXT NOT NULL,
    birth_place TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_states (
    user_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL,
    tariff_id INTEGER,
    form_json TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tariff_id INTEGER NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_payment_id TEXT,
    created_at TEXT NOT NULL,
    paid_at TEXT,
    comment TEXT,
    meta_json TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    message_type TEXT NOT NULL,
    text TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tariff_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    report_text TEXT NOT NULL,
    report_json TEXT,
    llm_provider TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (profile_id) REFERENCES user_profiles (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    is_followup_open INTEGER NOT NULL DEFAULT 1,
    followup_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admins (
    tg_id TEXT PRIMARY KEY,
    username TEXT,
    created_at TEXT NOT NULL,
    added_by TEXT
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_by_tg_id TEXT,
    segment TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (created_by_tg_id) REFERENCES admins (tg_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS broadcast_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broadcast_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    sent_at TEXT,
    FOREIGN KEY (broadcast_id) REFERENCES broadcasts (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tariff_policies (
    tariff_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    system_prompt_report TEXT NOT NULL,
    user_prompt_template_report TEXT NOT NULL,
    system_prompt_followup TEXT NOT NULL,
    followup_limit INTEGER NOT NULL,
    followup_window_hours INTEGER NOT NULL,
    followup_rules TEXT NOT NULL,
    output_format TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    report_id INTEGER,
    session_id INTEGER,
    purpose TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_id TEXT,
    latency_ms INTEGER,
    ok INTEGER NOT NULL,
    error_text TEXT,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY (report_id) REFERENCES reports (id) ON DELETE SET NULL,
    FOREIGN KEY (session_id) REFERENCES report_sessions (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users (tg_id);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles (user_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_created_at ON user_profiles (created_at);

CREATE INDEX IF NOT EXISTS idx_purchases_user_id ON purchases (user_id);
CREATE INDEX IF NOT EXISTS idx_purchases_created_at ON purchases (created_at);

CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages (user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages (created_at);

CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports (user_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports (created_at);

CREATE INDEX IF NOT EXISTS idx_report_sessions_report_id ON report_sessions (report_id);
CREATE INDEX IF NOT EXISTS idx_report_sessions_user_id ON report_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_report_sessions_created_at ON report_sessions (created_at);

CREATE INDEX IF NOT EXISTS idx_admins_tg_id ON admins (tg_id);
CREATE INDEX IF NOT EXISTS idx_admins_created_at ON admins (created_at);

CREATE INDEX IF NOT EXISTS idx_broadcasts_created_at ON broadcasts (created_at);
CREATE INDEX IF NOT EXISTS idx_broadcasts_created_by_tg_id ON broadcasts (created_by_tg_id);

CREATE INDEX IF NOT EXISTS idx_broadcast_logs_user_id ON broadcast_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_logs_broadcast_id ON broadcast_logs (broadcast_id);

CREATE INDEX IF NOT EXISTS idx_tariff_policies_updated_at ON tariff_policies (updated_at);

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_user_id ON llm_call_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_llm_call_logs_report_id ON llm_call_logs (report_id);
CREATE INDEX IF NOT EXISTS idx_llm_call_logs_created_at ON llm_call_logs (created_at);
