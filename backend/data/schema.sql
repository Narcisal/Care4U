CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS elder_memories (
    id BIGSERIAL PRIMARY KEY,
    elder_id VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    sentiment VARCHAR(32) NOT NULL DEFAULT 'neutral',
    importance REAL NOT NULL DEFAULT 0.3
        CHECK (importance >= 0.0 AND importance <= 1.0),
    memory_type VARCHAR(32) NOT NULL DEFAULT 'short',
    topic_tags TEXT[] NOT NULL DEFAULT '{}',
    spoken_at TIMESTAMP,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    persona_id VARCHAR(64) NOT NULL DEFAULT 'ai',
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_elder_memories_elder_id
    ON elder_memories (elder_id);

CREATE INDEX IF NOT EXISTS idx_elder_memories_importance
    ON elder_memories (elder_id, importance DESC);

CREATE INDEX IF NOT EXISTS idx_elder_memories_created_at
    ON elder_memories (elder_id, created_at DESC);
