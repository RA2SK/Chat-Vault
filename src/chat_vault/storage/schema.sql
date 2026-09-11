-- Chat Vault 初始数据库结构
-- 数据库：SQLite
-- 注意：MessageRevision 暂不持久化，待消息编辑业务稳定后再加入。

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin'
        CHECK (role IN ('admin', 'user'))
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('success', 'partial', 'failed')),
    total_count INTEGER NOT NULL DEFAULT 0
        CHECK (total_count >= 0),
    success_count INTEGER NOT NULL DEFAULT 0
        CHECK (success_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0
        CHECK (failed_count >= 0),
    source_type TEXT NOT NULL DEFAULT 'chatbox',
    format_key TEXT NOT NULL DEFAULT 'chatbox.v2',
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_import_batches_file_hash
    ON import_batches(file_hash);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_archive TEXT,
    source_entry TEXT,
    raw_data TEXT,
    created_at TEXT,
    updated_at TEXT,
    is_published INTEGER NOT NULL DEFAULT 0
        CHECK (is_published IN (0, 1)),
    import_batch_id INTEGER,
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(id)
        ON DELETE SET NULL,
    UNIQUE (source_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_import_batch
    ON conversations(import_batch_id);

CREATE TABLE IF NOT EXISTS branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    branch_index INTEGER NOT NULL
        CHECK (branch_index >= 0),
    fork_message_source_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    is_current INTEGER NOT NULL DEFAULT 0
        CHECK (is_current IN (0, 1)),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        ON DELETE CASCADE,
    UNIQUE (source_id)
);

CREATE INDEX IF NOT EXISTS idx_branches_conversation
    ON branches(conversation_id);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    thinking TEXT NOT NULL DEFAULT '',
    model TEXT,
    position INTEGER NOT NULL
        CHECK (position >= 0),
    timestamp TEXT,
    edited_at TEXT,
    edited_by INTEGER,
    FOREIGN KEY (branch_id) REFERENCES branches(id)
        ON DELETE CASCADE,
    FOREIGN KEY (edited_by) REFERENCES users(id)
        ON DELETE SET NULL,
    UNIQUE (source_id),
    UNIQUE (branch_id, position)
);

CREATE INDEX IF NOT EXISTS idx_messages_branch_position
    ON messages(branch_id, position);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    message_source_id TEXT,
    attach_type TEXT NOT NULL
        CHECK (attach_type IN ('image', 'file', 'other')),
    source_ref TEXT NOT NULL,
    display_name TEXT,
    mime_type TEXT,
    checksum_algorithm TEXT,
    checksum_value TEXT,
    size INTEGER
        CHECK (size IS NULL OR size >= 0),
    FOREIGN KEY (branch_id) REFERENCES branches(id)
        ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id)
        ON DELETE CASCADE,
    UNIQUE (message_id, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_attachments_message
    ON attachments(message_id);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER,
    message_id INTEGER,
    target_type TEXT NOT NULL
        CHECK (target_type IN ('conversation', 'message')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by INTEGER,
    nickname TEXT NOT NULL DEFAULT 'anonymous',
    is_deleted INTEGER NOT NULL DEFAULT 0
        CHECK (is_deleted IN (0, 1)),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id)
        ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE SET NULL,
    CHECK (
        (target_type = 'conversation' AND conversation_id IS NOT NULL AND message_id IS NULL)
        OR
        (target_type = 'message' AND conversation_id IS NULL AND message_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_comments_conversation
    ON comments(conversation_id);

CREATE INDEX IF NOT EXISTS idx_comments_message
    ON comments(message_id);

CREATE TABLE IF NOT EXISTS admin_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    mark_type TEXT NOT NULL
        CHECK (mark_type IN ('highlight', 'pin', 'other')),
    created_at TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0
        CHECK (is_deleted IN (0, 1)),
    FOREIGN KEY (message_id) REFERENCES messages(id)
        ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_admin_marks_message
    ON admin_marks(message_id);

COMMIT;
