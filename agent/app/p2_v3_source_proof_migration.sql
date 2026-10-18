-- Agent-local append-only P2 v3 proof schema. Version 004 only defines durable
-- structures and row-local integrity guards; Stage A adds no proof publisher.

CREATE TABLE p2_v3_execution_cohorts (
    cohort_sha256 TEXT PRIMARY KEY CHECK (length(cohort_sha256)=64),
    manifest_kind TEXT NOT NULL CHECK (manifest_kind IN ('production','synthetic_test')),
    profile_id TEXT NOT NULL CHECK (profile_id='p2.read-paged-prepayment-refund.v3-candidate'),
    api_version TEXT NOT NULL CHECK (api_version='3.0.0'),
    semantic_version TEXT NOT NULL CHECK (semantic_version='2.1.0'),
    operations_version TEXT NOT NULL CHECK (operations_version='2.1.0'),
    trajectory_version TEXT NOT NULL CHECK (trajectory_version='2.0.0'),
    schema_bundle_sha256 TEXT NOT NULL CHECK (length(schema_bundle_sha256)=64),
    source_manifest_sha256 TEXT NOT NULL CHECK (length(source_manifest_sha256)=64),
    contract_source_sha256 TEXT NOT NULL CHECK (length(contract_source_sha256)=64),
    safe_config_sha256 TEXT NOT NULL CHECK (length(safe_config_sha256)=64),
    component_count INTEGER NOT NULL CHECK (component_count BETWEEN 1 AND 64),
    created_at TEXT NOT NULL
);

CREATE TABLE p2_v3_execution_cohort_components (
    cohort_sha256 TEXT NOT NULL,
    component_path TEXT NOT NULL CHECK (length(component_path) BETWEEN 1 AND 512),
    component_role TEXT NOT NULL CHECK (length(component_role) BETWEEN 1 AND 64),
    byte_count INTEGER NOT NULL CHECK (byte_count BETWEEN 0 AND 8388608),
    component_sha256 TEXT NOT NULL CHECK (length(component_sha256)=64),
    PRIMARY KEY (cohort_sha256, component_path),
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_turn_execution_pins (
    turn_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256)=64),
    profile_id TEXT NOT NULL CHECK (profile_id='p2.read-paged-prepayment-refund.v3-candidate'),
    api_version TEXT NOT NULL,
    semantic_version TEXT NOT NULL,
    operations_version TEXT NOT NULL,
    trajectory_version TEXT NOT NULL,
    schema_bundle_sha256 TEXT NOT NULL CHECK (length(schema_bundle_sha256)=64),
    source_manifest_sha256 TEXT NOT NULL CHECK (length(source_manifest_sha256)=64),
    contract_source_sha256 TEXT NOT NULL CHECK (length(contract_source_sha256)=64),
    safe_config_sha256 TEXT NOT NULL CHECK (length(safe_config_sha256)=64),
    created_at TEXT NOT NULL,
    PRIMARY KEY (turn_id, owner_user_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    CHECK (api_version='3.0.0' AND semantic_version='2.1.0' AND operations_version='2.1.0' AND trajectory_version='2.0.0')
);

CREATE TABLE p2_v3_query_descriptor_bindings (
    logical_query_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    admission_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation>=1),
    input_seq INTEGER NOT NULL CHECK (input_seq>=1),
    input_digest TEXT NOT NULL CHECK (length(input_digest)=64),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch>=0),
    criteria_json TEXT NOT NULL CHECK (length(criteria_json)<=32768),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest)=64),
    scope_json TEXT NOT NULL CHECK (length(scope_json)<=32768),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest)=64),
    selected_refs_json TEXT NOT NULL CHECK (length(selected_refs_json)<=4096),
    selected_refs_digest TEXT NOT NULL CHECK (length(selected_refs_digest)=64),
    normalized_criteria_digest TEXT NOT NULL CHECK (length(normalized_criteria_digest)=64),
    context_revision INTEGER NOT NULL CHECK (context_revision>=1),
    cohort_sha256 TEXT NOT NULL CHECK (length(cohort_sha256)=64),
    normalized_descriptor_json TEXT NOT NULL CHECK (length(normalized_descriptor_json)<=49152),
    normalized_descriptor_sha256 TEXT NOT NULL CHECK (length(normalized_descriptor_sha256)=64),
    created_at TEXT NOT NULL,
    PRIMARY KEY (logical_query_id, owner_user_id, turn_id),
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id) REFERENCES p2_v3_queries(logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions(admission_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT
);

-- Every reserved GET is privately assigned to its admission or real query
-- attempt before dispatch. This is the chain/table cap index, not a second
-- counter; usage is derived from existing 003 charge events.
CREATE TABLE p2_v3_capture_chain_reservations (
    reservation_id TEXT PRIMARY KEY,
    reservation_event_kind TEXT NOT NULL DEFAULT 'reserved' CHECK (reservation_event_kind='reserved'),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL,
    reservation_binding_kind TEXT NOT NULL CHECK (reservation_binding_kind IN ('admission','query_attempt')),
    reservation_admission_id TEXT,
    reservation_logical_query_id TEXT,
    reservation_query_attempt_id TEXT,
    capture_chain_kind TEXT NOT NULL CHECK (capture_chain_kind IN ('admission','query_attempt')),
    capture_chain_id TEXT NOT NULL CHECK (length(capture_chain_id) BETWEEN 1 AND 80),
    capture_chain_logical_query_id TEXT,
    capture_chain_attempt_id TEXT,
    table_get_ordinal INTEGER NOT NULL CHECK (table_get_ordinal BETWEEN 0 AND 3),
    chain_sequence INTEGER NOT NULL CHECK (chain_sequence BETWEEN 0 AND 9223372036854775807),
    source_role TEXT NOT NULL CHECK (length(source_role) BETWEEN 1 AND 80),
    source_table TEXT NOT NULL CHECK (source_table IN (
        'activities','activity_members','ledger_units','participants',
        'sub_activity_participants','participant_claims','expenses','payments','splits',
        'expense_debts','prepayment_accounts','prepayment_usages','transfers',
        'transfer_components')),
    generation INTEGER NOT NULL CHECK (generation>=1),
    input_seq INTEGER NOT NULL CHECK (input_seq>=1),
    input_digest TEXT NOT NULL CHECK (length(input_digest)=64),
    claim_epoch INTEGER NOT NULL CHECK (claim_epoch>=0),
    authority_epoch INTEGER NOT NULL CHECK (authority_epoch>=0),
    context_revision INTEGER NOT NULL CHECK (context_revision>=1),
    reserved_at TEXT NOT NULL,
    CHECK (
        (source_table='activities' AND source_role IN ('activity','financial_version','scope_label')) OR
        (source_table='activity_members' AND source_role='membership') OR
        (source_table='ledger_units' AND source_role IN ('ledger_unit','scope_label')) OR
        (source_table='participants' AND source_role IN ('participant','scope_label')) OR
        (source_table='sub_activity_participants' AND source_role='ledger_unit') OR
        (source_table='participant_claims' AND source_role='actor') OR
        (source_table='expenses' AND source_role IN ('expense','refund_parent')) OR
        (source_table IN ('payments','splits') AND source_role='expense') OR
        (source_table='expense_debts' AND source_role='debt') OR
        (source_table='prepayment_accounts' AND source_role='prepayment_account') OR
        (source_table='prepayment_usages' AND source_role='prepayment_usage') OR
        (source_table IN ('transfers','transfer_components') AND source_role='prepayment_return')
    ),
    UNIQUE (capture_chain_id, chain_sequence),
    UNIQUE (reservation_id, owner_user_id, turn_id),
    FOREIGN KEY (reservation_id, reservation_event_kind, owner_user_id, turn_id)
        REFERENCES p2_v3_charge_events(reservation_id, event_kind, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (reservation_admission_id) REFERENCES p2_v3_source_admissions(admission_id) ON DELETE RESTRICT,
    FOREIGN KEY (reservation_logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries(logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (reservation_query_attempt_id) REFERENCES p2_v3_query_attempts(attempt_id) ON DELETE RESTRICT,
    FOREIGN KEY (capture_chain_logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries(logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (capture_chain_attempt_id) REFERENCES p2_v3_query_attempts(attempt_id) ON DELETE RESTRICT,
    CHECK ((reservation_binding_kind='admission' AND reservation_admission_id IS NOT NULL
                AND reservation_logical_query_id IS NULL AND reservation_query_attempt_id IS NULL)
        OR (reservation_binding_kind='query_attempt' AND reservation_admission_id IS NULL
                AND reservation_logical_query_id IS NOT NULL AND reservation_query_attempt_id IS NOT NULL)),
    CHECK ((capture_chain_kind='admission' AND capture_chain_id=reservation_admission_id
                AND capture_chain_logical_query_id IS NULL AND capture_chain_attempt_id IS NULL)
        OR (capture_chain_kind='query_attempt' AND capture_chain_logical_query_id IS NOT NULL
                AND capture_chain_attempt_id=capture_chain_id)),
    CHECK ((reservation_binding_kind='query_attempt' AND capture_chain_kind='query_attempt'
                AND reservation_logical_query_id=capture_chain_logical_query_id
                AND reservation_query_attempt_id=capture_chain_attempt_id)
        OR (reservation_binding_kind='admission' AND reservation_admission_id IS NOT NULL))
);
CREATE INDEX p2_v3_capture_chain_lookup_idx ON p2_v3_capture_chain_reservations
    (owner_user_id, turn_id, capture_chain_id, source_table, chain_sequence);

CREATE TABLE p2_v3_source_get_receipts (
    source_receipt_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL UNIQUE,
    reservation_id TEXT NOT NULL UNIQUE,
    reservation_event_kind TEXT NOT NULL DEFAULT 'settled' CHECK (reservation_event_kind='settled'),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL,
    binding_kind TEXT NOT NULL CHECK (binding_kind IN ('admission','query_attempt')),
    admission_id TEXT,
    logical_query_id TEXT,
    query_attempt_id TEXT,
    page_index INTEGER CHECK (page_index IS NULL OR page_index BETWEEN 0 AND 63),
    source_role TEXT NOT NULL CHECK (length(source_role) BETWEEN 1 AND 80),
    source_table TEXT NOT NULL CHECK (length(source_table) BETWEEN 1 AND 80),
    request_sha256 TEXT NOT NULL CHECK (length(request_sha256)=64),
    raw_body_sha256 TEXT NOT NULL CHECK (length(raw_body_sha256)=64),
    typed_dto_sha256 TEXT NOT NULL CHECK (length(typed_dto_sha256)=64),
    source_rows_sha256 TEXT NOT NULL CHECK (length(source_rows_sha256)=64),
    http_status INTEGER NOT NULL CHECK (http_status BETWEEN 200 AND 299),
    content_range TEXT NOT NULL CHECK (length(content_range)<=512),
    range_start INTEGER NOT NULL CHECK (range_start>=0),
    returned_count INTEGER NOT NULL CHECK (returned_count BETWEEN 0 AND 16),
    known_total INTEGER CHECK (known_total IS NULL OR known_total>=0),
    response_bytes INTEGER NOT NULL CHECK (response_bytes BETWEEN 0 AND 1048576),
    observed_at TEXT NOT NULL,
    elapsed_us INTEGER NOT NULL CHECK (elapsed_us>=0),
    accepted_at TEXT NOT NULL,
    UNIQUE (source_receipt_id, owner_user_id, turn_id),
    FOREIGN KEY (capture_id) REFERENCES p2_v3_wire_captures(capture_id) ON DELETE RESTRICT,
    FOREIGN KEY (reservation_id, reservation_event_kind, owner_user_id, turn_id)
        REFERENCES p2_v3_charge_events(reservation_id, event_kind, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions(admission_id) ON DELETE RESTRICT,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries(logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (query_attempt_id) REFERENCES p2_v3_query_attempts(attempt_id) ON DELETE RESTRICT,
    CHECK ((binding_kind='admission' AND admission_id IS NOT NULL AND logical_query_id IS NULL AND query_attempt_id IS NULL AND page_index IS NULL)
        OR (binding_kind='query_attempt' AND admission_id IS NULL AND logical_query_id IS NOT NULL AND query_attempt_id IS NOT NULL AND page_index IS NOT NULL))
);

CREATE TABLE p2_v3_admission_source_receipts (
    admission_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 127),
    source_receipt_id TEXT NOT NULL,
    private_scope_sha256 TEXT NOT NULL CHECK (length(private_scope_sha256)=64),
    source_role TEXT NOT NULL CHECK (length(source_role) BETWEEN 1 AND 80),
    PRIMARY KEY (admission_id, ordinal),
    UNIQUE (admission_id, source_receipt_id),
    FOREIGN KEY (admission_id) REFERENCES p2_v3_source_admissions(admission_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_query_result_receipts (
    query_result_receipt_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL,
    logical_query_id TEXT NOT NULL,
    query_attempt_id TEXT NOT NULL,
    page_index INTEGER NOT NULL CHECK (page_index BETWEEN 0 AND 63),
    query_evidence_ref TEXT NOT NULL CHECK (length(query_evidence_ref) BETWEEN 24 AND 68),
    query_ref TEXT NOT NULL CHECK (length(query_ref) BETWEEN 24 AND 68),
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest)=64),
    normalized_criteria_digest TEXT NOT NULL CHECK (length(normalized_criteria_digest)=64),
    scope_digest TEXT NOT NULL CHECK (length(scope_digest)=64),
    per_activity_financial_versions_json TEXT NOT NULL CHECK (length(per_activity_financial_versions_json)<=8192),
    historical_payload_json TEXT NOT NULL CHECK (length(historical_payload_json)<=262144),
    historical_payload_sha256 TEXT NOT NULL CHECK (length(historical_payload_sha256)=64),
    projection_sha256 TEXT NOT NULL CHECK (length(projection_sha256)=64),
    source_query_complete INTEGER NOT NULL CHECK (source_query_complete IN (0,1)),
    model_projection_complete INTEGER NOT NULL CHECK (model_projection_complete IN (0,1)),
    has_more INTEGER NOT NULL CHECK (has_more IN (0,1)),
    zero_classification TEXT NOT NULL CHECK (zero_classification IN ('not_zero','backend_zero','post_filter_zero','unknown_or_partial')),
    source_total INTEGER CHECK (source_total IS NULL OR source_total>=0),
    matched_total INTEGER CHECK (matched_total IS NULL OR matched_total>=0),
    page_count INTEGER NOT NULL CHECK (page_count BETWEEN 0 AND 32),
    observed_at TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (logical_query_id, turn_id, owner_user_id)
        REFERENCES p2_v3_queries(logical_query_id, turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (query_attempt_id) REFERENCES p2_v3_query_attempts(attempt_id) ON DELETE RESTRICT,
    UNIQUE (logical_query_id, query_attempt_id, page_index),
    UNIQUE (query_result_receipt_id, owner_user_id, turn_id),
    CHECK ((zero_classification IN ('backend_zero','post_filter_zero') AND source_query_complete=1)
        OR zero_classification IN ('not_zero','unknown_or_partial'))
);

CREATE TABLE p2_v3_query_result_gets (
    query_result_receipt_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 31),
    source_receipt_id TEXT NOT NULL,
    PRIMARY KEY (query_result_receipt_id, ordinal),
    UNIQUE (query_result_receipt_id, source_receipt_id),
    FOREIGN KEY (query_result_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_query_result_receipts(query_result_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_entity_locators (
    locator_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    entity_ref TEXT NOT NULL CHECK (length(entity_ref) BETWEEN 24 AND 68),
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('activity','participant','ledger_unit','expense','payment','split','debt','refund','prepayment_account','prepayment_usage','prepayment_return')),
    private_entity_id TEXT NOT NULL,
    private_activity_id TEXT,
    private_ledger_unit_id TEXT,
    cohort_sha256 TEXT NOT NULL,
    created_from_receipt_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (owner_user_id, turn_id, entity_ref, entity_kind),
    UNIQUE (locator_id, owner_user_id, turn_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (created_from_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_query_fact_proofs (
    fact_proof_id TEXT PRIMARY KEY,
    query_result_receipt_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    query_evidence_ref TEXT NOT NULL CHECK (length(query_evidence_ref) BETWEEN 24 AND 68),
    fact_ref TEXT NOT NULL CHECK (length(fact_ref) BETWEEN 24 AND 68),
    fact_kind TEXT NOT NULL CHECK (fact_kind IN ('activity','expense','debt','refund_event','prepayment_account','prepayment_usage','prepayment_return_event')),
    activity_ref TEXT,
    scope_ref TEXT,
    financial_version TEXT CHECK (financial_version IS NULL OR length(financial_version)<=20),
    exact_fact_json TEXT NOT NULL CHECK (length(exact_fact_json)<=32768),
    exact_fact_sha256 TEXT NOT NULL CHECK (length(exact_fact_sha256)=64),
    created_at TEXT NOT NULL,
    UNIQUE (query_result_receipt_id, fact_ref),
    UNIQUE (fact_proof_id, owner_user_id, turn_id),
    FOREIGN KEY (query_result_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_query_result_receipts(query_result_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_query_fact_sources (
    fact_proof_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 255),
    source_receipt_id TEXT NOT NULL,
    source_role TEXT NOT NULL CHECK (length(source_role) BETWEEN 1 AND 80),
    source_row_sha256 TEXT NOT NULL CHECK (length(source_row_sha256)=64),
    PRIMARY KEY (fact_proof_id, ordinal),
    UNIQUE (fact_proof_id, source_receipt_id, source_role),
    FOREIGN KEY (fact_proof_id, owner_user_id, turn_id)
        REFERENCES p2_v3_query_fact_proofs(fact_proof_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_activity_collection_qev_proofs (
    collection_proof_id TEXT PRIMARY KEY,
    query_result_receipt_id TEXT NOT NULL UNIQUE,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    query_evidence_ref TEXT NOT NULL CHECK (length(query_evidence_ref) BETWEEN 24 AND 68),
    private_collection_query_id TEXT NOT NULL,
    private_collection_locator_id TEXT NOT NULL,
    criteria_digest TEXT NOT NULL CHECK (length(criteria_digest)=64),
    normalized_criteria_digest TEXT NOT NULL CHECK (length(normalized_criteria_digest)=64),
    complete_zero_kind TEXT CHECK (complete_zero_kind IS NULL OR complete_zero_kind IN ('backend_zero','post_filter_zero')),
    created_at TEXT NOT NULL,
    UNIQUE (collection_proof_id, owner_user_id, turn_id),
    FOREIGN KEY (query_result_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_query_result_receipts(query_result_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_activity_collection_members (
    collection_proof_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 63),
    activity_ref TEXT NOT NULL CHECK (length(activity_ref) BETWEEN 24 AND 68),
    private_activity_locator_id TEXT NOT NULL,
    private_membership_proof_id TEXT NOT NULL,
    activity_source_receipt_id TEXT NOT NULL,
    membership_source_receipt_id TEXT NOT NULL,
    PRIMARY KEY (collection_proof_id, ordinal),
    UNIQUE (collection_proof_id, activity_ref),
    FOREIGN KEY (collection_proof_id, owner_user_id, turn_id)
        REFERENCES p2_v3_activity_collection_qev_proofs(collection_proof_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (private_activity_locator_id, owner_user_id, turn_id)
        REFERENCES p2_v3_entity_locators(locator_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (activity_source_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (membership_source_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_metadata_source_proofs (
    metadata_proof_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL,
    entity_ref TEXT NOT NULL CHECK (length(entity_ref) BETWEEN 24 AND 68),
    entity_kind TEXT NOT NULL CHECK (length(entity_kind) BETWEEN 1 AND 40),
    scope_ref TEXT NOT NULL CHECK (length(scope_ref) BETWEEN 24 AND 68),
    private_entity_locator_id TEXT NOT NULL,
    private_scope_locator_id TEXT NOT NULL,
    source_field_role TEXT NOT NULL CHECK (length(source_field_role) BETWEEN 1 AND 80),
    source_receipt_id TEXT NOT NULL,
    source_version TEXT,
    source_row_updated_at TEXT,
    observed_at TEXT NOT NULL,
    source_value_sha256 TEXT NOT NULL CHECK (length(source_value_sha256)=64),
    created_at TEXT NOT NULL,
    UNIQUE (metadata_proof_id, owner_user_id, turn_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (private_entity_locator_id, owner_user_id, turn_id)
        REFERENCES p2_v3_entity_locators(locator_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (private_scope_locator_id, owner_user_id, turn_id)
        REFERENCES p2_v3_entity_locators(locator_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (source_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_source_get_receipts(source_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    CHECK ((source_version IS NOT NULL AND source_row_updated_at IS NULL) OR (source_version IS NULL AND source_row_updated_at IS NOT NULL))
);

CREATE TABLE p2_v3_protected_outputs (
    protected_output_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL,
    event_seq INTEGER NOT NULL CHECK (event_seq>=1),
    output_kind TEXT NOT NULL CHECK (output_kind IN ('answer','clarification','proposal_intent','control','nonbusiness')),
    provenance_kind TEXT NOT NULL CHECK (provenance_kind IN ('source_free','source_bearing')),
    historical_payload_json TEXT NOT NULL CHECK (length(historical_payload_json)<=262144),
    historical_payload_sha256 TEXT NOT NULL CHECK (length(historical_payload_sha256)=64),
    generation INTEGER NOT NULL CHECK (generation>=1),
    input_seq INTEGER NOT NULL CHECK (input_seq>=1),
    input_digest TEXT NOT NULL CHECK (length(input_digest)=64),
    context_revision INTEGER NOT NULL CHECK (context_revision>=1),
    proof_set_sha256 TEXT NOT NULL CHECK (length(proof_set_sha256)=64),
    created_at TEXT NOT NULL,
    UNIQUE (turn_id, owner_user_id, event_seq),
    UNIQUE (protected_output_id, owner_user_id, turn_id),
    FOREIGN KEY (turn_id, owner_user_id) REFERENCES p2_v3_turns(turn_id, owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY (cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY (turn_id, event_seq) REFERENCES events(turn_id, seq) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_output_fact_links (
    protected_output_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    card_ordinal INTEGER NOT NULL CHECK (card_ordinal BETWEEN 0 AND 255),
    fact_proof_id TEXT NOT NULL,
    public_card_json TEXT NOT NULL CHECK (length(public_card_json)<=32768),
    public_card_sha256 TEXT NOT NULL CHECK (length(public_card_sha256)=64),
    PRIMARY KEY (protected_output_id, card_ordinal),
    FOREIGN KEY (protected_output_id, owner_user_id, turn_id)
        REFERENCES p2_v3_protected_outputs(protected_output_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (fact_proof_id, owner_user_id, turn_id)
        REFERENCES p2_v3_query_fact_proofs(fact_proof_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_output_query_links (
    protected_output_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 63),
    query_result_receipt_id TEXT NOT NULL,
    query_evidence_ref TEXT NOT NULL CHECK (length(query_evidence_ref) BETWEEN 24 AND 68),
    PRIMARY KEY (protected_output_id, ordinal),
    FOREIGN KEY (protected_output_id, owner_user_id, turn_id)
        REFERENCES p2_v3_protected_outputs(protected_output_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (query_result_receipt_id, owner_user_id, turn_id)
        REFERENCES p2_v3_query_result_receipts(query_result_receipt_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_output_metadata_links (
    protected_output_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 127),
    metadata_proof_id TEXT NOT NULL,
    PRIMARY KEY (protected_output_id, ordinal),
    FOREIGN KEY (protected_output_id, owner_user_id, turn_id)
        REFERENCES p2_v3_protected_outputs(protected_output_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (metadata_proof_id, owner_user_id, turn_id)
        REFERENCES p2_v3_metadata_source_proofs(metadata_proof_id, owner_user_id, turn_id) ON DELETE RESTRICT
);

CREATE TABLE p2_v3_output_event_links (
    protected_output_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    event_seq INTEGER NOT NULL CHECK (event_seq>=1),
    PRIMARY KEY (protected_output_id, event_seq),
    UNIQUE (turn_id, event_seq),
    FOREIGN KEY (protected_output_id, owner_user_id, turn_id)
        REFERENCES p2_v3_protected_outputs(protected_output_id, owner_user_id, turn_id) ON DELETE RESTRICT,
    FOREIGN KEY (turn_id, event_seq) REFERENCES events(turn_id, seq) ON DELETE RESTRICT
);

CREATE INDEX p2_v3_cohort_component_role_idx ON p2_v3_execution_cohort_components(cohort_sha256, component_role);
CREATE INDEX p2_v3_capture_chain_source_idx ON p2_v3_capture_chain_reservations
    (turn_id, owner_user_id, capture_chain_id, source_table, reservation_id);
CREATE INDEX p2_v3_source_receipt_turn_idx ON p2_v3_source_get_receipts(owner_user_id, turn_id, accepted_at);
CREATE INDEX p2_v3_result_query_idx ON p2_v3_query_result_receipts(owner_user_id, turn_id, logical_query_id, page_index);
CREATE INDEX p2_v3_fact_proof_result_idx ON p2_v3_query_fact_proofs(query_result_receipt_id, fact_kind);
CREATE INDEX p2_v3_metadata_entity_idx ON p2_v3_metadata_source_proofs(owner_user_id, turn_id, entity_ref, source_field_role);
CREATE INDEX p2_v3_protected_output_event_idx ON p2_v3_protected_outputs(owner_user_id, turn_id, event_seq);

CREATE TRIGGER p2_v3_turn_pin_matches_rows
BEFORE INSERT ON p2_v3_turn_execution_pins
WHEN NOT EXISTS (
    SELECT 1 FROM p2_v3_turns t JOIN p2_v3_execution_cohorts c
      ON c.cohort_sha256=NEW.cohort_sha256
    WHERE t.turn_id=NEW.turn_id AND t.owner_user_id=NEW.owner_user_id
      AND t.profile_id=NEW.profile_id AND t.api_version=NEW.api_version
      AND t.semantic_version=NEW.semantic_version AND t.operations_version=NEW.operations_version
      AND t.trajectory_version=NEW.trajectory_version
      AND t.schema_bundle_sha256=NEW.schema_bundle_sha256
      AND t.source_manifest_sha256=NEW.source_manifest_sha256
      AND t.contract_source_sha256=NEW.contract_source_sha256
      AND c.manifest_kind IN ('production','synthetic_test') AND c.profile_id=NEW.profile_id
      AND c.api_version=NEW.api_version AND c.semantic_version=NEW.semantic_version
      AND c.operations_version=NEW.operations_version AND c.trajectory_version=NEW.trajectory_version
      AND c.schema_bundle_sha256=NEW.schema_bundle_sha256
      AND c.source_manifest_sha256=NEW.source_manifest_sha256
      AND c.contract_source_sha256=NEW.contract_source_sha256
      AND c.safe_config_sha256=NEW.safe_config_sha256 AND c.cohort_sha256=NEW.manifest_sha256
)
BEGIN SELECT RAISE(ABORT,'P2 v3 turn pin does not match verified execution cohort'); END;

CREATE TRIGGER p2_v3_source_receipt_matches_capture
BEFORE INSERT ON p2_v3_source_get_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM p2_v3_wire_captures w JOIN p2_v3_charge_events e
      ON e.reservation_id=NEW.reservation_id AND e.event_kind='settled'
     AND e.owner_user_id=NEW.owner_user_id AND e.turn_id=NEW.turn_id
    WHERE w.capture_id=NEW.capture_id AND w.reservation_id=NEW.reservation_id
      AND w.owner_user_id=NEW.owner_user_id AND w.turn_id=NEW.turn_id
      AND w.request_digest=NEW.request_sha256 AND w.raw_body_sha256=NEW.raw_body_sha256
      AND w.http_status=NEW.http_status AND COALESCE(w.content_range,'')=NEW.content_range
      AND w.returned_count=NEW.returned_count AND w.response_bytes=NEW.response_bytes
      AND e.request_digest=NEW.request_sha256 AND e.raw_body_sha256=NEW.raw_body_sha256
      AND e.actual_response_bytes=NEW.response_bytes AND e.stage='backend_get'
      AND e.source_role=NEW.source_role
)
BEGIN SELECT RAISE(ABORT,'P2 v3 source receipt does not match the exact settled capture'); END;

CREATE TRIGGER p2_v3_chain_reservation_matches_charge
BEFORE INSERT ON p2_v3_capture_chain_reservations
WHEN NOT EXISTS (
    SELECT 1 FROM p2_v3_charge_events e
    WHERE e.reservation_id=NEW.reservation_id AND e.event_kind='reserved'
      AND e.owner_user_id=NEW.owner_user_id AND e.turn_id=NEW.turn_id
      AND e.stage='backend_get' AND e.source_role=NEW.source_role
      AND e.generation=NEW.generation AND e.claim_epoch=NEW.claim_epoch
      AND e.authority_epoch=NEW.authority_epoch AND e.context_revision=NEW.context_revision
      AND (
          (NEW.reservation_binding_kind='admission' AND EXISTS (
              SELECT 1 FROM p2_v3_source_admissions s
              WHERE s.admission_id=NEW.reservation_admission_id
                AND s.owner_user_id=NEW.owner_user_id AND s.turn_id=NEW.turn_id
                AND s.generation=NEW.generation AND s.input_seq=NEW.input_seq
                AND s.input_digest=NEW.input_digest AND s.claim_epoch=NEW.claim_epoch
                AND s.authority_epoch=NEW.authority_epoch
                AND s.context_revision=NEW.context_revision
          ))
          OR (NEW.reservation_binding_kind='query_attempt' AND EXISTS (
              SELECT 1 FROM p2_v3_queries q
              JOIN p2_v3_query_attempts a ON a.logical_query_id=q.logical_query_id
                AND a.owner_user_id=q.owner_user_id AND a.turn_id=q.turn_id
              JOIN p2_v3_source_admissions s ON s.admission_id=a.admission_id
              WHERE q.logical_query_id=NEW.reservation_logical_query_id
                AND q.owner_user_id=NEW.owner_user_id AND q.turn_id=NEW.turn_id
                AND a.attempt_id=NEW.reservation_query_attempt_id
                AND a.generation=NEW.generation AND a.authority_epoch=NEW.authority_epoch
                AND a.criteria_digest=q.criteria_digest AND a.scope_digest=q.scope_digest
                AND a.attempt_state='started'
                AND s.generation=NEW.generation AND s.input_seq=NEW.input_seq
                AND s.input_digest=NEW.input_digest AND s.claim_epoch=NEW.claim_epoch
                AND s.authority_epoch=NEW.authority_epoch
                AND s.context_revision=NEW.context_revision
          ))
      )
      AND ((NEW.reservation_binding_kind='admission' AND e.admission_id=NEW.reservation_admission_id
             AND e.logical_query_id IS NULL AND e.query_attempt_id IS NULL)
        OR (NEW.reservation_binding_kind='query_attempt' AND e.admission_id IS NULL
             AND e.logical_query_id=NEW.reservation_logical_query_id
             AND e.query_attempt_id=NEW.reservation_query_attempt_id))
      AND (
          (NEW.reservation_binding_kind='admission' AND (
              (NEW.source_table='activities' AND NEW.source_role IN ('activity','financial_version','scope_label')) OR
              (NEW.source_table='activity_members' AND NEW.source_role='membership') OR
              (NEW.source_table='participants' AND NEW.source_role IN ('participant','scope_label')) OR
              (NEW.source_table='ledger_units' AND NEW.source_role IN ('ledger_unit','scope_label')) OR
              (NEW.source_table='sub_activity_participants' AND NEW.source_role='ledger_unit') OR
              (NEW.source_table='participant_claims' AND NEW.source_role='actor')
          ))
          OR (NEW.reservation_binding_kind='query_attempt' AND EXISTS (
              SELECT 1 FROM p2_v3_queries role_query
              WHERE role_query.logical_query_id=NEW.reservation_logical_query_id
                AND role_query.owner_user_id=NEW.owner_user_id AND role_query.turn_id=NEW.turn_id
                AND (
                    (role_query.operation='read.activities' AND NEW.source_role IN ('activity','membership','participant','scope_label','actor','financial_version')) OR
                    (role_query.operation='read.expenses' AND NEW.source_role IN ('activity','membership','participant','ledger_unit','expense','actor','scope_label','financial_version')) OR
                    (role_query.operation='read.debts' AND NEW.source_role IN ('activity','membership','participant','ledger_unit','expense','debt','financial_version')) OR
                    (role_query.operation='read.refund_events' AND NEW.source_role IN ('activity','membership','expense','refund_parent','financial_version')) OR
                    (role_query.operation='read.prepayment_accounts' AND NEW.source_role IN ('activity','membership','prepayment_account','financial_version')) OR
                    (role_query.operation='read.prepayment_usages' AND NEW.source_role IN ('activity','membership','participant','ledger_unit','expense','debt','prepayment_account','prepayment_usage','financial_version')) OR
                    (role_query.operation='read.prepayment_return_events' AND NEW.source_role IN ('activity','membership','prepayment_account','prepayment_return','financial_version'))
                )
          ))
      )
      AND (NEW.capture_chain_kind='admission' OR EXISTS (
          SELECT 1 FROM p2_v3_query_attempts a JOIN p2_v3_queries q
            ON q.logical_query_id=a.logical_query_id AND q.owner_user_id=a.owner_user_id
           AND q.turn_id=a.turn_id
          JOIN p2_v3_source_admissions s ON s.admission_id=a.admission_id
          WHERE a.attempt_id=NEW.capture_chain_attempt_id
            AND a.logical_query_id=NEW.capture_chain_logical_query_id
            AND a.owner_user_id=NEW.owner_user_id AND a.turn_id=NEW.turn_id
            AND a.generation=NEW.generation AND a.authority_epoch=NEW.authority_epoch
            AND a.criteria_digest=q.criteria_digest AND a.scope_digest=q.scope_digest
            AND a.attempt_state='started'
            AND s.generation=NEW.generation AND s.input_seq=NEW.input_seq
            AND s.input_digest=NEW.input_digest AND s.claim_epoch=NEW.claim_epoch
            AND s.authority_epoch=NEW.authority_epoch
            AND s.context_revision=NEW.context_revision
            AND ((NEW.reservation_binding_kind='query_attempt'
                    AND a.attempt_id=NEW.reservation_query_attempt_id
                    AND a.logical_query_id=NEW.reservation_logical_query_id)
              OR (NEW.reservation_binding_kind='admission'
                    AND a.admission_id=NEW.reservation_admission_id))
      ))
)
BEGIN SELECT RAISE(ABORT,'P2 v3 capture-chain link does not match its reserved GET'); END;

CREATE TRIGGER p2_v3_query_descriptor_matches_query
BEFORE INSERT ON p2_v3_query_descriptor_bindings
WHEN NOT EXISTS (
    SELECT 1 FROM p2_v3_queries q
    WHERE q.logical_query_id=NEW.logical_query_id AND q.owner_user_id=NEW.owner_user_id
      AND q.turn_id=NEW.turn_id AND q.admission_id=NEW.admission_id
      AND q.generation=NEW.generation AND q.input_seq=NEW.input_seq
      AND q.input_digest=NEW.input_digest AND q.authority_epoch=NEW.authority_epoch
      AND q.criteria_json=NEW.criteria_json AND q.criteria_digest=NEW.criteria_digest
      AND q.scope_json=NEW.scope_json AND q.scope_digest=NEW.scope_digest
)
BEGIN SELECT RAISE(ABORT,'P2 v3 normalized query descriptor differs from immutable query'); END;

CREATE TRIGGER p2_v3_query_result_matches_attempt
BEFORE INSERT ON p2_v3_query_result_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM p2_v3_queries q JOIN p2_v3_query_attempts a
      ON a.logical_query_id=q.logical_query_id AND a.owner_user_id=q.owner_user_id AND a.turn_id=q.turn_id
    WHERE q.logical_query_id=NEW.logical_query_id AND q.owner_user_id=NEW.owner_user_id
      AND q.turn_id=NEW.turn_id AND q.criteria_digest=NEW.criteria_digest
      AND q.scope_digest=NEW.scope_digest AND a.attempt_id=NEW.query_attempt_id
      AND a.page_index=NEW.page_index AND a.criteria_digest=NEW.criteria_digest
      AND a.scope_digest=NEW.scope_digest AND a.attempt_state='started'
)
BEGIN SELECT RAISE(ABORT,'P2 v3 result receipt does not match its immutable query attempt'); END;

CREATE TRIGGER p2_v3_output_event_matches_event
BEFORE INSERT ON p2_v3_output_event_links
WHEN NOT EXISTS (
    SELECT 1 FROM events e WHERE e.turn_id=NEW.turn_id AND e.seq=NEW.event_seq
)
BEGIN SELECT RAISE(ABORT,'P2 v3 output event link has no canonical event'); END;

CREATE TRIGGER p2_v3_execution_cohorts_no_update BEFORE UPDATE ON p2_v3_execution_cohorts BEGIN SELECT RAISE(ABORT,'P2 v3 execution cohorts are immutable'); END;
CREATE TRIGGER p2_v3_execution_cohorts_no_delete BEFORE DELETE ON p2_v3_execution_cohorts BEGIN SELECT RAISE(ABORT,'P2 v3 execution cohorts are immutable'); END;
CREATE TRIGGER p2_v3_execution_components_no_update BEFORE UPDATE ON p2_v3_execution_cohort_components BEGIN SELECT RAISE(ABORT,'P2 v3 execution components are immutable'); END;
CREATE TRIGGER p2_v3_execution_components_no_delete BEFORE DELETE ON p2_v3_execution_cohort_components BEGIN SELECT RAISE(ABORT,'P2 v3 execution components are immutable'); END;
CREATE TRIGGER p2_v3_execution_pins_no_update BEFORE UPDATE ON p2_v3_turn_execution_pins BEGIN SELECT RAISE(ABORT,'P2 v3 execution pins are immutable'); END;
CREATE TRIGGER p2_v3_execution_pins_no_delete BEFORE DELETE ON p2_v3_turn_execution_pins BEGIN SELECT RAISE(ABORT,'P2 v3 execution pins are immutable'); END;
CREATE TRIGGER p2_v3_capture_chain_no_update BEFORE UPDATE ON p2_v3_capture_chain_reservations BEGIN SELECT RAISE(ABORT,'P2 v3 capture chain reservations are immutable'); END;
CREATE TRIGGER p2_v3_capture_chain_no_delete BEFORE DELETE ON p2_v3_capture_chain_reservations BEGIN SELECT RAISE(ABORT,'P2 v3 capture chain reservations are immutable'); END;
CREATE TRIGGER p2_v3_query_descriptor_no_update BEFORE UPDATE ON p2_v3_query_descriptor_bindings BEGIN SELECT RAISE(ABORT,'P2 v3 query descriptors are immutable'); END;
CREATE TRIGGER p2_v3_query_descriptor_no_delete BEFORE DELETE ON p2_v3_query_descriptor_bindings BEGIN SELECT RAISE(ABORT,'P2 v3 query descriptors are immutable'); END;
CREATE TRIGGER p2_v3_source_receipts_no_update BEFORE UPDATE ON p2_v3_source_get_receipts BEGIN SELECT RAISE(ABORT,'P2 v3 source receipts are immutable'); END;
CREATE TRIGGER p2_v3_source_receipts_no_delete BEFORE DELETE ON p2_v3_source_get_receipts BEGIN SELECT RAISE(ABORT,'P2 v3 source receipts are immutable'); END;
CREATE TRIGGER p2_v3_admission_receipts_no_update BEFORE UPDATE ON p2_v3_admission_source_receipts BEGIN SELECT RAISE(ABORT,'P2 v3 admission receipts are immutable'); END;
CREATE TRIGGER p2_v3_admission_receipts_no_delete BEFORE DELETE ON p2_v3_admission_source_receipts BEGIN SELECT RAISE(ABORT,'P2 v3 admission receipts are immutable'); END;
CREATE TRIGGER p2_v3_result_receipts_no_update BEFORE UPDATE ON p2_v3_query_result_receipts BEGIN SELECT RAISE(ABORT,'P2 v3 result receipts are immutable'); END;
CREATE TRIGGER p2_v3_result_receipts_no_delete BEFORE DELETE ON p2_v3_query_result_receipts BEGIN SELECT RAISE(ABORT,'P2 v3 result receipts are immutable'); END;
CREATE TRIGGER p2_v3_result_gets_no_update BEFORE UPDATE ON p2_v3_query_result_gets BEGIN SELECT RAISE(ABORT,'P2 v3 result GET links are immutable'); END;
CREATE TRIGGER p2_v3_result_gets_no_delete BEFORE DELETE ON p2_v3_query_result_gets BEGIN SELECT RAISE(ABORT,'P2 v3 result GET links are immutable'); END;
CREATE TRIGGER p2_v3_locators_no_update BEFORE UPDATE ON p2_v3_entity_locators BEGIN SELECT RAISE(ABORT,'P2 v3 entity locators are immutable'); END;
CREATE TRIGGER p2_v3_locators_no_delete BEFORE DELETE ON p2_v3_entity_locators BEGIN SELECT RAISE(ABORT,'P2 v3 entity locators are immutable'); END;
CREATE TRIGGER p2_v3_fact_proofs_no_update BEFORE UPDATE ON p2_v3_query_fact_proofs BEGIN SELECT RAISE(ABORT,'P2 v3 fact proofs are immutable'); END;
CREATE TRIGGER p2_v3_fact_proofs_no_delete BEFORE DELETE ON p2_v3_query_fact_proofs BEGIN SELECT RAISE(ABORT,'P2 v3 fact proofs are immutable'); END;
CREATE TRIGGER p2_v3_fact_sources_no_update BEFORE UPDATE ON p2_v3_query_fact_sources BEGIN SELECT RAISE(ABORT,'P2 v3 fact sources are immutable'); END;
CREATE TRIGGER p2_v3_fact_sources_no_delete BEFORE DELETE ON p2_v3_query_fact_sources BEGIN SELECT RAISE(ABORT,'P2 v3 fact sources are immutable'); END;
CREATE TRIGGER p2_v3_collection_proofs_no_update BEFORE UPDATE ON p2_v3_activity_collection_qev_proofs BEGIN SELECT RAISE(ABORT,'P2 v3 collection proofs are immutable'); END;
CREATE TRIGGER p2_v3_collection_proofs_no_delete BEFORE DELETE ON p2_v3_activity_collection_qev_proofs BEGIN SELECT RAISE(ABORT,'P2 v3 collection proofs are immutable'); END;
CREATE TRIGGER p2_v3_collection_members_no_update BEFORE UPDATE ON p2_v3_activity_collection_members BEGIN SELECT RAISE(ABORT,'P2 v3 collection members are immutable'); END;
CREATE TRIGGER p2_v3_collection_members_no_delete BEFORE DELETE ON p2_v3_activity_collection_members BEGIN SELECT RAISE(ABORT,'P2 v3 collection members are immutable'); END;
CREATE TRIGGER p2_v3_metadata_proofs_no_update BEFORE UPDATE ON p2_v3_metadata_source_proofs BEGIN SELECT RAISE(ABORT,'P2 v3 metadata proofs are immutable'); END;
CREATE TRIGGER p2_v3_metadata_proofs_no_delete BEFORE DELETE ON p2_v3_metadata_source_proofs BEGIN SELECT RAISE(ABORT,'P2 v3 metadata proofs are immutable'); END;
CREATE TRIGGER p2_v3_protected_outputs_no_update BEFORE UPDATE ON p2_v3_protected_outputs BEGIN SELECT RAISE(ABORT,'P2 v3 protected outputs are immutable'); END;
CREATE TRIGGER p2_v3_protected_outputs_no_delete BEFORE DELETE ON p2_v3_protected_outputs BEGIN SELECT RAISE(ABORT,'P2 v3 protected outputs are immutable'); END;
CREATE TRIGGER p2_v3_output_fact_links_no_update BEFORE UPDATE ON p2_v3_output_fact_links BEGIN SELECT RAISE(ABORT,'P2 v3 output links are immutable'); END;
CREATE TRIGGER p2_v3_output_fact_links_no_delete BEFORE DELETE ON p2_v3_output_fact_links BEGIN SELECT RAISE(ABORT,'P2 v3 output links are immutable'); END;
CREATE TRIGGER p2_v3_output_query_links_no_update BEFORE UPDATE ON p2_v3_output_query_links BEGIN SELECT RAISE(ABORT,'P2 v3 output links are immutable'); END;
CREATE TRIGGER p2_v3_output_query_links_no_delete BEFORE DELETE ON p2_v3_output_query_links BEGIN SELECT RAISE(ABORT,'P2 v3 output links are immutable'); END;
CREATE TRIGGER p2_v3_output_metadata_links_no_update BEFORE UPDATE ON p2_v3_output_metadata_links BEGIN SELECT RAISE(ABORT,'P2 v3 output links are immutable'); END;
CREATE TRIGGER p2_v3_output_metadata_links_no_delete BEFORE DELETE ON p2_v3_output_metadata_links BEGIN SELECT RAISE(ABORT,'P2 v3 output links are immutable'); END;
CREATE TRIGGER p2_v3_output_event_links_no_update BEFORE UPDATE ON p2_v3_output_event_links BEGIN SELECT RAISE(ABORT,'P2 v3 event links are immutable'); END;
CREATE TRIGGER p2_v3_output_event_links_no_delete BEFORE DELETE ON p2_v3_output_event_links BEGIN SELECT RAISE(ABORT,'P2 v3 event links are immutable'); END;
