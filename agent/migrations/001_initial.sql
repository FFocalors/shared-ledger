CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    title TEXT,
    default_activity_hint TEXT,
    create_request_id TEXT NOT NULL,
    create_payload_hash TEXT NOT NULL,
    create_request_json TEXT NOT NULL,
    create_response_json TEXT NOT NULL,
    private_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_user_id, create_request_id),
    UNIQUE (session_id, owner_user_id)
);

CREATE TABLE turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    request_payload_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    state TEXT NOT NULL,
    state_revision INTEGER NOT NULL CHECK (state_revision >= 1),
    step TEXT NOT NULL,
    execution_id TEXT,
    execution_resolution TEXT,
    record_json TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    checkpoint_revision INTEGER NOT NULL CHECK (checkpoint_revision >= 1),
    queue_order INTEGER NOT NULL UNIQUE CHECK (queue_order >= 1),
    claim_token TEXT,
    claim_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (turn_id, session_id, owner_user_id),
    UNIQUE (turn_id, owner_user_id),
    UNIQUE (owner_user_id, client_request_id),
    FOREIGN KEY (session_id, owner_user_id)
        REFERENCES sessions (session_id, owner_user_id)
        ON DELETE RESTRICT
);

CREATE INDEX turns_queue_order_idx
    ON turns (state, queue_order, turn_id);
CREATE INDEX turns_recovery_idx
    ON turns (state, updated_at, turn_id);

CREATE TABLE events (
    turn_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 1),
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (turn_id, seq),
    FOREIGN KEY (turn_id, session_id, owner_user_id)
        REFERENCES turns (turn_id, session_id, owner_user_id)
        ON DELETE RESTRICT
);

CREATE INDEX events_owner_cursor_idx
    ON events (owner_user_id, turn_id, seq);

CREATE TRIGGER events_append_only_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TRIGGER events_append_only_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TABLE proposals (
    proposal_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (proposal_id, owner_user_id, session_id, turn_id),
    FOREIGN KEY (session_id, owner_user_id)
        REFERENCES sessions (session_id, owner_user_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (turn_id, session_id, owner_user_id)
        REFERENCES turns (turn_id, session_id, owner_user_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX one_pending_proposal_per_session_idx
    ON proposals (session_id)
    WHERE status = 'pending';
CREATE INDEX proposals_owner_session_idx
    ON proposals (owner_user_id, session_id, updated_at);

CREATE TRIGGER sessions_identity_immutable
BEFORE UPDATE OF session_id, owner_user_id, create_request_id ON sessions
BEGIN
    SELECT RAISE(ABORT, 'session identity is immutable');
END;

CREATE TRIGGER turns_identity_immutable
BEFORE UPDATE OF turn_id, session_id, owner_user_id, client_request_id ON turns
BEGIN
    SELECT RAISE(ABORT, 'turn identity is immutable');
END;

CREATE TRIGGER proposals_identity_immutable
BEFORE UPDATE OF proposal_id, owner_user_id, session_id, turn_id ON proposals
BEGIN
    SELECT RAISE(ABORT, 'proposal identity is immutable');
END;
