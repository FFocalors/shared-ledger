-- Internal local-Agent persistence for the default-off P2 candidate profile.
-- This migration is explicitly loaded as Store schema version 2; it is not a
-- business database migration and never stores Auth credentials or source facts.

CREATE TABLE p2_candidate_turns (
    turn_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    profile_id TEXT NOT NULL CHECK (profile_id = 'p2.read-paged-prepayment-refund.v2-candidate'),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    input_seq INTEGER NOT NULL CHECK (input_seq >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    turn_state_revision INTEGER NOT NULL CHECK (turn_state_revision >= 1),
    claim_epoch INTEGER NOT NULL DEFAULT 0 CHECK (claim_epoch >= 0),
    read_epoch INTEGER NOT NULL DEFAULT 0 CHECK (read_epoch >= 0),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('queued','active','waiting','terminal','invalidated')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    model_calls INTEGER NOT NULL DEFAULT 0 CHECK (model_calls BETWEEN 0 AND 6),
    logical_read_calls INTEGER NOT NULL DEFAULT 0 CHECK (logical_read_calls BETWEEN 0 AND 4),
    repair_calls INTEGER NOT NULL DEFAULT 0 CHECK (repair_calls BETWEEN 0 AND 1),
    active_used_us INTEGER NOT NULL DEFAULT 0 CHECK (active_used_us BETWEEN 0 AND 240000000),
    active_reserved_us INTEGER NOT NULL DEFAULT 0 CHECK (active_reserved_us BETWEEN 0 AND 240000000),
    backend_used_us INTEGER NOT NULL DEFAULT 0 CHECK (backend_used_us BETWEEN 0 AND 20000000),
    backend_reserved_us INTEGER NOT NULL DEFAULT 0 CHECK (backend_reserved_us BETWEEN 0 AND 20000000),
    get_attempts INTEGER NOT NULL DEFAULT 0 CHECK (get_attempts BETWEEN 0 AND 48),
    response_bytes INTEGER NOT NULL DEFAULT 0 CHECK (response_bytes BETWEEN 0 AND 4194304),
    bytes_reserved INTEGER NOT NULL DEFAULT 0 CHECK (bytes_reserved BETWEEN 0 AND 4194304),
    unknown_consumption INTEGER NOT NULL DEFAULT 0 CHECK (unknown_consumption IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (turn_id, owner_user_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES turns (turn_id, owner_user_id) ON DELETE RESTRICT,
    CHECK (active_used_us + active_reserved_us <= 240000000),
    CHECK (backend_used_us + backend_reserved_us <= 20000000),
    CHECK (backend_used_us + backend_reserved_us <= active_used_us + active_reserved_us),
    CHECK (response_bytes + bytes_reserved <= 4194304)
);

CREATE INDEX p2_candidate_owner_turn_idx ON p2_candidate_turns (owner_user_id, turn_id, lifecycle);
CREATE TRIGGER p2_candidate_turn_identity_immutable
BEFORE UPDATE OF turn_id, owner_user_id, profile_id ON p2_candidate_turns
BEGIN SELECT RAISE(ABORT, 'P2 candidate Turn identity is immutable'); END;
CREATE TRIGGER p2_candidate_turn_no_delete
BEFORE DELETE ON p2_candidate_turns
BEGIN SELECT RAISE(ABORT, 'P2 candidate Turn history is retained'); END;

CREATE TABLE p2_candidate_charge_events (
    charge_event_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('reserved','settled','unknown')),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    profile_id TEXT NOT NULL CHECK (profile_id = 'p2.read-paged-prepayment-refund.v2-candidate'),
    stage TEXT NOT NULL CHECK (stage IN ('model','repair','backend_get','backend_processing','local_processing')),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 0),
    read_epoch INTEGER NOT NULL CHECK (read_epoch >= 1),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    logical_query_id TEXT,
    active_limit_us INTEGER NOT NULL CHECK (active_limit_us > 0 AND active_limit_us <= 240000000),
    backend_limit_us INTEGER NOT NULL DEFAULT 0 CHECK (backend_limit_us BETWEEN 0 AND 20000000),
    response_bytes_limit INTEGER NOT NULL DEFAULT 0 CHECK (response_bytes_limit BETWEEN 0 AND 4194304),
    actual_active_us INTEGER,
    actual_backend_us INTEGER,
    actual_response_bytes INTEGER,
    overrun_active_us INTEGER NOT NULL DEFAULT 0 CHECK (overrun_active_us >= 0),
    overrun_backend_us INTEGER NOT NULL DEFAULT 0 CHECK (overrun_backend_us >= 0),
    overrun_response_bytes INTEGER NOT NULL DEFAULT 0 CHECK (overrun_response_bytes >= 0),
    request_digest TEXT,
    raw_body_digest TEXT,
    unknown_flag INTEGER NOT NULL DEFAULT 0 CHECK (unknown_flag IN (0,1)),
    occurred_at TEXT NOT NULL,
    UNIQUE (reservation_id, event_kind),
    UNIQUE (reservation_id, event_kind, owner_user_id, turn_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_candidate_turns (turn_id, owner_user_id) ON DELETE RESTRICT,
    CHECK ((stage = 'backend_get' AND backend_limit_us > 0 AND response_bytes_limit > 0 AND logical_query_id IS NOT NULL AND request_digest IS NOT NULL)
        OR (stage = 'backend_processing' AND backend_limit_us > 0 AND response_bytes_limit = 0 AND request_digest IS NULL AND logical_query_id IS NULL)
        OR (stage IN ('model','repair','local_processing') AND backend_limit_us = 0 AND response_bytes_limit = 0 AND request_digest IS NULL AND logical_query_id IS NULL)),
    CHECK ((event_kind = 'reserved' AND actual_active_us IS NULL AND actual_backend_us IS NULL AND actual_response_bytes IS NULL AND raw_body_digest IS NULL AND unknown_flag = 0 AND overrun_active_us = 0 AND overrun_backend_us = 0 AND overrun_response_bytes = 0)
        OR (event_kind = 'settled' AND actual_active_us IS NOT NULL AND actual_backend_us IS NOT NULL AND actual_response_bytes IS NOT NULL AND unknown_flag = 0 AND overrun_active_us = 0 AND overrun_backend_us = 0 AND overrun_response_bytes = 0)
        OR (event_kind = 'unknown' AND actual_active_us IS NOT NULL AND actual_backend_us IS NOT NULL AND actual_response_bytes IS NOT NULL AND unknown_flag = 1 AND raw_body_digest IS NULL)),
    CHECK (actual_active_us IS NULL OR actual_active_us BETWEEN 0 AND active_limit_us),
    CHECK (actual_backend_us IS NULL OR actual_backend_us BETWEEN 0 AND backend_limit_us),
    CHECK (backend_limit_us <= active_limit_us),
    CHECK (actual_backend_us IS NULL OR actual_active_us IS NULL OR actual_backend_us <= actual_active_us),
    CHECK (actual_response_bytes IS NULL OR actual_response_bytes BETWEEN 0 AND response_bytes_limit),
    CHECK (raw_body_digest IS NULL OR length(raw_body_digest) = 64)
);

CREATE INDEX p2_candidate_charge_turn_idx ON p2_candidate_charge_events (turn_id, owner_user_id, occurred_at, reservation_id);

CREATE TABLE p2_candidate_queries (
    logical_query_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    profile_id TEXT NOT NULL CHECK (profile_id = 'p2.read-paged-prepayment-refund.v2-candidate'),
    operation TEXT NOT NULL CHECK (operation IN (
        'read.activities','read.expenses','read.debts','read.refund_events',
        'read.prepayment_accounts','read.prepayment_usages','read.prepayment_return_events')),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    input_seq INTEGER NOT NULL CHECK (input_seq >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    criteria_json TEXT NOT NULL CHECK (length(criteria_json) <= 32768),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest) = 64),
    scope_json TEXT NOT NULL CHECK (length(scope_json) <= 32768),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest) = 64),
    created_context_revision INTEGER NOT NULL CHECK (created_context_revision >= 1),
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_candidate_turns (turn_id, owner_user_id) ON DELETE RESTRICT,
    UNIQUE (logical_query_id, turn_id, owner_user_id)
);

CREATE INDEX p2_candidate_query_turn_idx ON p2_candidate_queries (turn_id, owner_user_id, generation, created_at);

CREATE TABLE p2_candidate_page_receipts (
    receipt_id TEXT PRIMARY KEY,
    logical_query_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    input_seq INTEGER NOT NULL CHECK (input_seq >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 0),
    read_epoch INTEGER NOT NULL CHECK (read_epoch >= 1),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    page_index INTEGER NOT NULL CHECK (page_index BETWEEN 0 AND 63),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest) = 64),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest) = 64),
    source_get_chain_digest TEXT NOT NULL CHECK (length(source_get_chain_digest) = 64),
    raw_body_digest TEXT NOT NULL CHECK (length(raw_body_digest) = 64),
    validated_dto_digest TEXT NOT NULL CHECK (length(validated_dto_digest) = 64),
    projection_digest TEXT NOT NULL CHECK (length(projection_digest) = 64),
    source_version_digest TEXT NOT NULL CHECK (length(source_version_digest) = 64),
    observed_at TEXT NOT NULL,
    source_query_complete INTEGER NOT NULL CHECK (source_query_complete IN (0,1)),
    model_page_has_more INTEGER NOT NULL CHECK (model_page_has_more IN (0,1)),
    next_page_ref_digest TEXT CHECK (next_page_ref_digest IS NULL OR length(next_page_ref_digest) = 64),
    receipt_digest TEXT NOT NULL CHECK (length(receipt_digest) = 64),
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_candidate_queries (logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    UNIQUE (logical_query_id, read_epoch, page_index),
    CHECK ((model_page_has_more = 1 AND next_page_ref_digest IS NOT NULL)
        OR (model_page_has_more = 0 AND next_page_ref_digest IS NULL))
);

CREATE TABLE p2_candidate_page_gets (
    receipt_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    settlement_event_kind TEXT NOT NULL DEFAULT 'settled' CHECK (settlement_event_kind = 'settled'),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (receipt_id, ordinal),
    UNIQUE (receipt_id, reservation_id),
    FOREIGN KEY (receipt_id) REFERENCES p2_candidate_page_receipts (receipt_id) ON DELETE RESTRICT,
    FOREIGN KEY (reservation_id, settlement_event_kind, owner_user_id, turn_id)
        REFERENCES p2_candidate_charge_events (reservation_id, event_kind, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TRIGGER p2_candidate_charge_events_append_only_update
BEFORE UPDATE ON p2_candidate_charge_events
BEGIN SELECT RAISE(ABORT, 'P2 candidate charge history is append-only'); END;
CREATE TRIGGER p2_candidate_charge_events_append_only_delete
BEFORE DELETE ON p2_candidate_charge_events
BEGIN SELECT RAISE(ABORT, 'P2 candidate charge history is append-only'); END;
CREATE TRIGGER p2_candidate_queries_append_only_update
BEFORE UPDATE ON p2_candidate_queries
BEGIN SELECT RAISE(ABORT, 'P2 candidate query descriptors are append-only'); END;
CREATE TRIGGER p2_candidate_queries_append_only_delete
BEFORE DELETE ON p2_candidate_queries
BEGIN SELECT RAISE(ABORT, 'P2 candidate query descriptors are append-only'); END;
CREATE TRIGGER p2_candidate_page_receipts_append_only_update
BEFORE UPDATE ON p2_candidate_page_receipts
BEGIN SELECT RAISE(ABORT, 'P2 candidate page receipts are append-only'); END;
CREATE TRIGGER p2_candidate_page_receipts_append_only_delete
BEFORE DELETE ON p2_candidate_page_receipts
BEGIN SELECT RAISE(ABORT, 'P2 candidate page receipts are append-only'); END;
CREATE TRIGGER p2_candidate_page_gets_append_only_update
BEFORE UPDATE ON p2_candidate_page_gets
BEGIN SELECT RAISE(ABORT, 'P2 candidate page source links are append-only'); END;
CREATE TRIGGER p2_candidate_page_gets_append_only_delete
BEFORE DELETE ON p2_candidate_page_gets
BEGIN SELECT RAISE(ABORT, 'P2 candidate page source links are append-only'); END;
