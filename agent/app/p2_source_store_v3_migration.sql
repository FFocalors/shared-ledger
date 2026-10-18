-- Agent-local append-only Store extension for the disabled P2 v3 candidate.
-- This is version 003 loaded by store.py. It is not a business database
-- migration and contains no credentials, raw response bodies, or source facts.

CREATE TABLE p2_v3_turns (
    turn_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    profile_id TEXT NOT NULL CHECK (profile_id = 'p2.read-paged-prepayment-refund.v3-candidate'),
    api_version TEXT NOT NULL CHECK (api_version = '3.0.0'),
    semantic_version TEXT NOT NULL CHECK (semantic_version = '2.1.0'),
    operations_version TEXT NOT NULL CHECK (operations_version = '2.1.0'),
    trajectory_version TEXT NOT NULL CHECK (trajectory_version = '2.0.0'),
    schema_bundle_sha256 TEXT NOT NULL CHECK (length(schema_bundle_sha256) = 64),
    source_manifest_sha256 TEXT NOT NULL CHECK (length(source_manifest_sha256) = 64),
    contract_source_sha256 TEXT NOT NULL CHECK (length(contract_source_sha256) = 64),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    input_seq INTEGER NOT NULL CHECK (input_seq >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    turn_state_revision INTEGER NOT NULL CHECK (turn_state_revision >= 1),
    claim_epoch INTEGER NOT NULL DEFAULT 0 CHECK (claim_epoch >= 0),
    authority_epoch INTEGER NOT NULL DEFAULT 0 CHECK (authority_epoch >= 0),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('queued','active','waiting','terminal','invalidated')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    model_calls INTEGER NOT NULL DEFAULT 0 CHECK (model_calls BETWEEN 0 AND 6),
    model_reserved_calls INTEGER NOT NULL DEFAULT 0 CHECK (model_reserved_calls BETWEEN 0 AND 6),
    repair_calls INTEGER NOT NULL DEFAULT 0 CHECK (repair_calls BETWEEN 0 AND 1),
    repair_reserved_calls INTEGER NOT NULL DEFAULT 0 CHECK (repair_reserved_calls BETWEEN 0 AND 1),
    logical_read_calls INTEGER NOT NULL DEFAULT 0 CHECK (logical_read_calls BETWEEN 0 AND 4),
    active_used_us INTEGER NOT NULL DEFAULT 0 CHECK (active_used_us BETWEEN 0 AND 240000000),
    active_reserved_us INTEGER NOT NULL DEFAULT 0 CHECK (active_reserved_us BETWEEN 0 AND 240000000),
    backend_used_us INTEGER NOT NULL DEFAULT 0 CHECK (backend_used_us BETWEEN 0 AND 20000000),
    backend_reserved_us INTEGER NOT NULL DEFAULT 0 CHECK (backend_reserved_us BETWEEN 0 AND 20000000),
    get_attempts INTEGER NOT NULL DEFAULT 0 CHECK (get_attempts BETWEEN 0 AND 48),
    get_reserved INTEGER NOT NULL DEFAULT 0 CHECK (get_reserved BETWEEN 0 AND 48),
    response_bytes INTEGER NOT NULL DEFAULT 0 CHECK (response_bytes BETWEEN 0 AND 4194304),
    bytes_reserved INTEGER NOT NULL DEFAULT 0 CHECK (bytes_reserved BETWEEN 0 AND 4194304),
    historical_unknown_consumption INTEGER NOT NULL DEFAULT 0 CHECK (historical_unknown_consumption IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (turn_id, owner_user_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES turns (turn_id, owner_user_id) ON DELETE RESTRICT,
    CHECK (model_calls + model_reserved_calls <= 6),
    CHECK (active_used_us + active_reserved_us <= 240000000),
    CHECK (backend_used_us + backend_reserved_us <= 20000000),
    CHECK (backend_used_us + backend_reserved_us <= active_used_us + active_reserved_us),
    CHECK (response_bytes + bytes_reserved <= 4194304),
    CHECK (get_attempts + get_reserved <= 48),
    CHECK (repair_calls <= model_calls)
);

CREATE INDEX p2_v3_owner_turn_idx ON p2_v3_turns (owner_user_id, turn_id, lifecycle);
CREATE TRIGGER p2_v3_turn_identity_immutable
BEFORE UPDATE OF turn_id, owner_user_id, profile_id, api_version, semantic_version,
    operations_version, trajectory_version, schema_bundle_sha256, source_manifest_sha256,
    contract_source_sha256 ON p2_v3_turns
BEGIN SELECT RAISE(ABORT, 'P2 v3 Turn profile pin is immutable'); END;
CREATE TRIGGER p2_v3_turn_no_delete
BEFORE DELETE ON p2_v3_turns
BEGIN SELECT RAISE(ABORT, 'P2 v3 Turn history is retained'); END;
CREATE TRIGGER p2_v3_excludes_v2_family
BEFORE INSERT ON p2_v3_turns
WHEN EXISTS (SELECT 1 FROM p2_candidate_turns WHERE turn_id = NEW.turn_id)
BEGIN SELECT RAISE(ABORT, 'Turn already belongs to the v2 candidate family'); END;
CREATE TRIGGER p2_v2_excludes_v3_family
BEFORE INSERT ON p2_candidate_turns
WHEN EXISTS (SELECT 1 FROM p2_v3_turns WHERE turn_id = NEW.turn_id)
BEGIN SELECT RAISE(ABORT, 'Turn already belongs to the v3 candidate family'); END;

CREATE TABLE p2_v3_charge_events (
    event_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('reserved','dispatch_started','settled','known_no_dispatch','unknown')),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    profile_id TEXT NOT NULL CHECK (profile_id = 'p2.read-paged-prepayment-refund.v3-candidate'),
    stage TEXT NOT NULL CHECK (stage IN ('model','repair','backend_get','backend_processing','local_processing')),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 0),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    logical_query_id TEXT,
    query_attempt_id TEXT,
    admission_id TEXT,
    source_role TEXT,
    active_limit_us INTEGER NOT NULL CHECK (active_limit_us > 0 AND active_limit_us <= 240000000),
    backend_limit_us INTEGER NOT NULL DEFAULT 0 CHECK (backend_limit_us BETWEEN 0 AND 20000000),
    response_bytes_limit INTEGER NOT NULL DEFAULT 0 CHECK (response_bytes_limit BETWEEN 0 AND 4194304),
    request_digest TEXT,
    prepared_request_sha256 TEXT,
    selected_model_key TEXT,
    validated_measurement_sha256 TEXT,
    actual_active_us INTEGER,
    actual_backend_us INTEGER,
    actual_response_bytes INTEGER,
    overrun_active_us INTEGER NOT NULL DEFAULT 0 CHECK (overrun_active_us >= 0),
    overrun_backend_us INTEGER NOT NULL DEFAULT 0 CHECK (overrun_backend_us >= 0),
    overrun_response_bytes INTEGER NOT NULL DEFAULT 0 CHECK (overrun_response_bytes >= 0),
    raw_body_sha256 TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE (reservation_id, event_kind),
    UNIQUE (reservation_id, event_kind, owner_user_id, turn_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns (turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries (logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (query_attempt_id) REFERENCES p2_v3_query_attempts (attempt_id) ON DELETE RESTRICT,
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions (admission_id) ON DELETE RESTRICT,
    CHECK (backend_limit_us <= active_limit_us),
    CHECK (actual_backend_us IS NULL OR actual_active_us IS NULL OR actual_backend_us <= actual_active_us),
    CHECK (raw_body_sha256 IS NULL OR length(raw_body_sha256) = 64),
    CHECK (request_digest IS NULL OR length(request_digest) = 64),
    CHECK (prepared_request_sha256 IS NULL OR length(prepared_request_sha256) = 64),
    CHECK (validated_measurement_sha256 IS NULL OR length(validated_measurement_sha256) = 64),
    CHECK (selected_model_key IS NULL OR length(selected_model_key) BETWEEN 1 AND 128),
    CHECK (
        (stage IN ('model','repair') AND event_kind='dispatch_started'
            AND prepared_request_sha256 IS NOT NULL AND selected_model_key IS NOT NULL
            AND validated_measurement_sha256 IS NOT NULL)
        OR (NOT (stage IN ('model','repair') AND event_kind='dispatch_started')
            AND prepared_request_sha256 IS NULL AND selected_model_key IS NULL
            AND validated_measurement_sha256 IS NULL)
    ),
    CHECK (
        (stage IN ('model','repair') AND backend_limit_us = 0 AND response_bytes_limit = 0
            AND logical_query_id IS NULL AND query_attempt_id IS NULL AND admission_id IS NULL AND source_role IS NULL
            AND request_digest IS NULL)
        OR (stage = 'backend_get' AND backend_limit_us > 0 AND response_bytes_limit > 0
            AND source_role IS NOT NULL AND request_digest IS NOT NULL
            AND ((logical_query_id IS NOT NULL AND query_attempt_id IS NOT NULL AND admission_id IS NULL)
                OR (logical_query_id IS NULL AND query_attempt_id IS NULL AND admission_id IS NOT NULL)))
        OR (stage = 'backend_processing' AND backend_limit_us > 0 AND response_bytes_limit = 0
            AND logical_query_id IS NULL AND query_attempt_id IS NULL AND admission_id IS NULL AND source_role IS NULL
            AND request_digest IS NULL)
        OR (stage = 'local_processing' AND backend_limit_us = 0 AND response_bytes_limit = 0
            AND logical_query_id IS NULL AND query_attempt_id IS NULL AND admission_id IS NULL AND source_role IS NULL
            AND request_digest IS NULL)
    ),
    CHECK (
        (event_kind = 'reserved' AND actual_active_us IS NULL AND actual_backend_us IS NULL
            AND actual_response_bytes IS NULL AND raw_body_sha256 IS NULL)
        OR (event_kind IN ('settled','known_no_dispatch','unknown')
            AND actual_active_us IS NOT NULL AND actual_backend_us IS NOT NULL
            AND actual_response_bytes IS NOT NULL)
        OR (event_kind = 'dispatch_started' AND actual_active_us IS NULL AND actual_backend_us IS NULL
            AND actual_response_bytes IS NULL AND raw_body_sha256 IS NULL)
    ),
    CHECK (actual_active_us IS NULL OR actual_active_us >= 0),
    CHECK (actual_backend_us IS NULL OR actual_backend_us >= 0),
    CHECK (actual_response_bytes IS NULL OR actual_response_bytes >= 0),
    CHECK (event_kind != 'known_no_dispatch' OR raw_body_sha256 IS NULL),
    CHECK (event_kind != 'unknown' OR raw_body_sha256 IS NULL)
);
CREATE INDEX p2_v3_charge_turn_idx ON p2_v3_charge_events (turn_id, owner_user_id, occurred_at, reservation_id);

CREATE TABLE p2_v3_source_admissions (
    admission_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    input_seq INTEGER NOT NULL CHECK (input_seq >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 0),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    ui_hint_digest TEXT CHECK (ui_hint_digest IS NULL OR length(ui_hint_digest) = 64),
    requested_scope_json TEXT NOT NULL CHECK (length(requested_scope_json) <= 8192),
    requested_scope_digest TEXT NOT NULL CHECK (length(requested_scope_digest) = 64),
    public_scope_digest TEXT NOT NULL CHECK (length(public_scope_digest) = 64),
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns (turn_id, owner_user_id) ON DELETE RESTRICT
);
CREATE INDEX p2_v3_admission_turn_idx ON p2_v3_source_admissions (turn_id, owner_user_id, generation, authority_epoch);

CREATE TABLE p2_v3_queries (
    logical_query_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    profile_id TEXT NOT NULL CHECK (profile_id = 'p2.read-paged-prepayment-refund.v3-candidate'),
    operation TEXT NOT NULL CHECK (operation IN (
        'read.activities','read.expenses','read.debts','read.refund_events',
        'read.prepayment_accounts','read.prepayment_usages','read.prepayment_return_events')),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    input_seq INTEGER NOT NULL CHECK (input_seq >= 1),
    input_digest TEXT NOT NULL CHECK (length(input_digest) = 64),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    criteria_json TEXT NOT NULL CHECK (length(criteria_json) <= 32768),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest) = 64),
    scope_json TEXT NOT NULL CHECK (length(scope_json) <= 32768),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest) = 64),
    created_context_revision INTEGER NOT NULL CHECK (created_context_revision >= 1),
    admission_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns (turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions (admission_id) ON DELETE RESTRICT,
    UNIQUE (logical_query_id, turn_id, owner_user_id)
);
CREATE INDEX p2_v3_query_turn_idx ON p2_v3_queries (turn_id, owner_user_id, generation, created_at);

CREATE TABLE p2_v3_query_attempts (
    attempt_id TEXT PRIMARY KEY,
    logical_query_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    attempt_seq INTEGER NOT NULL CHECK (attempt_seq >= 1),
    page_index INTEGER NOT NULL CHECK (page_index BETWEEN 0 AND 63),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest) = 64),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest) = 64),
    admission_id TEXT NOT NULL,
    attempt_state TEXT NOT NULL CHECK (attempt_state IN ('started','wire_only','stale','rejected')),
    source_version_digest TEXT CHECK (source_version_digest IS NULL OR length(source_version_digest) = 64),
    observed_at TEXT NOT NULL,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries (logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions (admission_id) ON DELETE RESTRICT,
    UNIQUE (logical_query_id, attempt_seq, page_index)
);
CREATE INDEX p2_v3_attempt_query_idx ON p2_v3_query_attempts (logical_query_id, attempt_seq, page_index);

CREATE TABLE p2_v3_wire_captures (
    capture_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL,
    reservation_event_kind TEXT NOT NULL DEFAULT 'settled' CHECK (reservation_event_kind = 'settled'),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    query_attempt_id TEXT,
    logical_query_id TEXT,
    admission_id TEXT,
    source_role TEXT NOT NULL,
    page_index INTEGER CHECK (page_index IS NULL OR page_index BETWEEN 0 AND 63),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    claim_epoch INTEGER NOT NULL CHECK (claim_epoch >= 0),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    raw_body_sha256 TEXT NOT NULL CHECK (length(raw_body_sha256) = 64),
    http_status INTEGER NOT NULL CHECK (http_status BETWEEN 100 AND 599),
    content_range TEXT,
    returned_count INTEGER NOT NULL CHECK (returned_count >= 0),
    response_bytes INTEGER NOT NULL CHECK (response_bytes >= 0),
    observed_at TEXT NOT NULL,
    capture_state TEXT NOT NULL DEFAULT 'cost_only' CHECK (capture_state = 'cost_only'),
    FOREIGN KEY (reservation_id, reservation_event_kind, owner_user_id, turn_id)
        REFERENCES p2_v3_charge_events (reservation_id, event_kind, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (query_attempt_id) REFERENCES p2_v3_query_attempts (attempt_id) ON DELETE RESTRICT,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries (logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions (admission_id) ON DELETE RESTRICT,
    CHECK ((logical_query_id IS NOT NULL AND admission_id IS NULL)
        OR (logical_query_id IS NULL AND admission_id IS NOT NULL)),
    UNIQUE (reservation_id),
    CHECK (content_range IS NULL OR length(content_range) <= 512),
    CHECK (length(source_role) <= 80)
);
CREATE INDEX p2_v3_capture_turn_idx ON p2_v3_wire_captures (turn_id, owner_user_id, observed_at, capture_id);

CREATE TABLE p2_v3_continuation_nonce_uses (
    nonce_sha256 TEXT PRIMARY KEY CHECK (length(nonce_sha256) = 64),
    logical_query_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    attempt_seq INTEGER NOT NULL CHECK (attempt_seq >= 1),
    page_index INTEGER NOT NULL CHECK (page_index BETWEEN 0 AND 63),
    consumed_at TEXT NOT NULL,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries (logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT
);
CREATE INDEX p2_v3_nonce_query_idx ON p2_v3_continuation_nonce_uses
    (logical_query_id, authority_epoch, attempt_seq, page_index);

CREATE TABLE p2_v3_continuation_nonce_issues (
    nonce_sha256 TEXT PRIMARY KEY CHECK (length(nonce_sha256) = 64),
    logical_query_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 0),
    attempt_seq INTEGER NOT NULL CHECK (attempt_seq >= 1),
    page_index INTEGER NOT NULL CHECK (page_index BETWEEN 0 AND 63),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest) = 64),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest) = 64),
    source_proof_sha256 TEXT NOT NULL CHECK (length(source_proof_sha256) = 64),
    projection_sha256 TEXT NOT NULL CHECK (length(projection_sha256) = 64),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries (logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (logical_query_id, attempt_seq, page_index)
        REFERENCES p2_v3_query_attempts (logical_query_id, attempt_seq, page_index) ON DELETE RESTRICT
);
CREATE INDEX p2_v3_nonce_issue_query_idx ON p2_v3_continuation_nonce_issues
    (logical_query_id, authority_epoch, attempt_seq, page_index);

CREATE TRIGGER p2_v3_charge_events_append_only_update
BEFORE UPDATE ON p2_v3_charge_events
BEGIN SELECT RAISE(ABORT, 'P2 v3 charge history is append-only'); END;
CREATE TRIGGER p2_v3_charge_events_append_only_delete
BEFORE DELETE ON p2_v3_charge_events
BEGIN SELECT RAISE(ABORT, 'P2 v3 charge history is append-only'); END;
CREATE TRIGGER p2_v3_admissions_append_only_update
BEFORE UPDATE ON p2_v3_source_admissions
BEGIN SELECT RAISE(ABORT, 'P2 v3 source admissions are append-only'); END;
CREATE TRIGGER p2_v3_admissions_append_only_delete
BEFORE DELETE ON p2_v3_source_admissions
BEGIN SELECT RAISE(ABORT, 'P2 v3 source admissions are append-only'); END;
CREATE TRIGGER p2_v3_queries_append_only_update
BEFORE UPDATE ON p2_v3_queries
BEGIN SELECT RAISE(ABORT, 'P2 v3 query descriptors are append-only'); END;
CREATE TRIGGER p2_v3_queries_append_only_delete
BEFORE DELETE ON p2_v3_queries
BEGIN SELECT RAISE(ABORT, 'P2 v3 query descriptors are append-only'); END;
CREATE TRIGGER p2_v3_attempts_append_only_update
BEFORE UPDATE ON p2_v3_query_attempts
BEGIN SELECT RAISE(ABORT, 'P2 v3 query attempts are append-only'); END;
CREATE TRIGGER p2_v3_attempts_append_only_delete
BEFORE DELETE ON p2_v3_query_attempts
BEGIN SELECT RAISE(ABORT, 'P2 v3 query attempts are append-only'); END;
CREATE TRIGGER p2_v3_captures_append_only_update
BEFORE UPDATE ON p2_v3_wire_captures
BEGIN SELECT RAISE(ABORT, 'P2 v3 wire captures are append-only'); END;
CREATE TRIGGER p2_v3_captures_append_only_delete
BEFORE DELETE ON p2_v3_wire_captures
BEGIN SELECT RAISE(ABORT, 'P2 v3 wire captures are append-only'); END;
CREATE TRIGGER p2_v3_nonce_uses_append_only_update
BEFORE UPDATE ON p2_v3_continuation_nonce_uses
BEGIN SELECT RAISE(ABORT, 'P2 v3 nonce use history is append-only'); END;
CREATE TRIGGER p2_v3_nonce_uses_append_only_delete
BEFORE DELETE ON p2_v3_continuation_nonce_uses
BEGIN SELECT RAISE(ABORT, 'P2 v3 nonce use history is append-only'); END;
CREATE TRIGGER p2_v3_nonce_issues_append_only_update
BEFORE UPDATE ON p2_v3_continuation_nonce_issues
BEGIN SELECT RAISE(ABORT, 'P2 v3 nonce issue history is append-only'); END;
CREATE TRIGGER p2_v3_nonce_issues_append_only_delete
BEFORE DELETE ON p2_v3_continuation_nonce_issues
BEGIN SELECT RAISE(ABORT, 'P2 v3 nonce issue history is append-only'); END;
