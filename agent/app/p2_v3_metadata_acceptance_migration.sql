-- D-only candidate V005 R2. Not applied, approved, or wired to Store.
-- Metadata admission acceptance only; no financial-query/QEV authorization.
-- Store must re-decode rows, recompute hashes, check current lease/claim/pin, and gate publication.

CREATE TABLE p2_v3_metadata_acceptance_batches (
    acceptance_id TEXT PRIMARY KEY CHECK(length(acceptance_id) BETWEEN 16 AND 80),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    cohort_sha256 TEXT NOT NULL CHECK(length(cohort_sha256)=64),
    admission_id TEXT NOT NULL,
    processing_reservation_id TEXT NOT NULL UNIQUE,
    reserved_event_id TEXT NOT NULL,
    reserved_event_kind TEXT NOT NULL DEFAULT 'reserved' CHECK(reserved_event_kind='reserved'),
    generation INTEGER NOT NULL CHECK(generation>=1),
    input_seq INTEGER NOT NULL CHECK(input_seq>=1),
    input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
    claim_epoch INTEGER NOT NULL CHECK(claim_epoch>=0),
    authority_epoch INTEGER NOT NULL CHECK(authority_epoch>=0),
    context_revision INTEGER NOT NULL CHECK(context_revision>=1),
    projection_sha256 TEXT NOT NULL CHECK(length(projection_sha256)=64),
    proof_set_sha256 TEXT NOT NULL CHECK(length(proof_set_sha256)=64),
    proof_count INTEGER NOT NULL CHECK(typeof(proof_count)='integer' AND proof_count BETWEEN 1 AND 129),
    created_at TEXT NOT NULL,
    UNIQUE(acceptance_id,owner_user_id,turn_id),
    FOREIGN KEY(turn_id,owner_user_id) REFERENCES p2_v3_turns(turn_id,owner_user_id) ON DELETE RESTRICT,
    FOREIGN KEY(cohort_sha256) REFERENCES p2_v3_execution_cohorts(cohort_sha256) ON DELETE RESTRICT,
    FOREIGN KEY(admission_id) REFERENCES p2_v3_source_admissions(admission_id) ON DELETE RESTRICT,
    FOREIGN KEY(processing_reservation_id,reserved_event_kind,owner_user_id,turn_id)
      REFERENCES p2_v3_charge_events(reservation_id,event_kind,owner_user_id,turn_id) ON DELETE RESTRICT
);

CREATE TRIGGER p2_v3_ma_batch_identity
BEFORE INSERT ON p2_v3_metadata_acceptance_batches
WHEN NOT EXISTS (
 SELECT 1 FROM p2_v3_source_admissions a
 JOIN p2_v3_turns t ON t.turn_id=a.turn_id AND t.owner_user_id=a.owner_user_id
 JOIN p2_v3_turn_execution_pins pin ON pin.turn_id=t.turn_id AND pin.owner_user_id=t.owner_user_id
 JOIN p2_v3_charge_events r ON r.reservation_id=NEW.processing_reservation_id
      AND r.event_id=NEW.reserved_event_id AND r.event_kind=NEW.reserved_event_kind
      AND r.owner_user_id=NEW.owner_user_id AND r.turn_id=NEW.turn_id
 WHERE a.admission_id=NEW.admission_id AND a.owner_user_id=NEW.owner_user_id AND a.turn_id=NEW.turn_id
   AND a.generation=NEW.generation AND a.input_seq=NEW.input_seq AND a.input_digest=NEW.input_digest
   AND a.claim_epoch=NEW.claim_epoch AND a.authority_epoch=NEW.authority_epoch
   AND a.context_revision=NEW.context_revision
   AND t.profile_id='p2.read-paged-prepayment-refund.v3-candidate'
   AND t.lifecycle='active' AND t.generation=NEW.generation AND t.input_seq=NEW.input_seq
   AND t.input_digest=NEW.input_digest AND t.claim_epoch=NEW.claim_epoch
   AND t.authority_epoch=NEW.authority_epoch AND t.context_revision=NEW.context_revision
   AND pin.cohort_sha256=NEW.cohort_sha256
   AND r.stage='backend_processing' AND r.profile_id=t.profile_id
   AND r.generation=NEW.generation AND r.claim_epoch=NEW.claim_epoch
   AND r.authority_epoch=NEW.authority_epoch AND r.context_revision=NEW.context_revision
   AND r.logical_query_id IS NULL AND r.query_attempt_id IS NULL AND r.admission_id IS NULL
   AND r.backend_limit_us>0 AND r.active_limit_us>=r.backend_limit_us
)
BEGIN SELECT RAISE(ABORT,'metadata batch identity/reservation mismatch'); END;

CREATE TABLE p2_v3_metadata_acceptance_proofs (
    acceptance_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 128),
    metadata_proof_id TEXT NOT NULL,
    source_receipt_id TEXT NOT NULL,
    PRIMARY KEY(acceptance_id,ordinal),
    UNIQUE(acceptance_id,metadata_proof_id),
    FOREIGN KEY(acceptance_id,owner_user_id,turn_id)
      REFERENCES p2_v3_metadata_acceptance_batches(acceptance_id,owner_user_id,turn_id) ON DELETE RESTRICT,
    FOREIGN KEY(metadata_proof_id,owner_user_id,turn_id)
      REFERENCES p2_v3_metadata_source_proofs(metadata_proof_id,owner_user_id,turn_id) ON DELETE RESTRICT,
    FOREIGN KEY(source_receipt_id,owner_user_id,turn_id)
      REFERENCES p2_v3_source_get_receipts(source_receipt_id,owner_user_id,turn_id) ON DELETE RESTRICT
);
CREATE TRIGGER p2_v3_ma_proof_matches_admission
BEFORE INSERT ON p2_v3_metadata_acceptance_proofs
WHEN NOT EXISTS (
 SELECT 1 FROM p2_v3_metadata_acceptance_batches b
 JOIN p2_v3_metadata_source_proofs p ON p.metadata_proof_id=NEW.metadata_proof_id
      AND p.owner_user_id=NEW.owner_user_id AND p.turn_id=NEW.turn_id
 JOIN p2_v3_source_get_receipts r ON r.source_receipt_id=NEW.source_receipt_id
      AND r.owner_user_id=NEW.owner_user_id AND r.turn_id=NEW.turn_id
 JOIN p2_v3_admission_source_receipts ar ON ar.admission_id=b.admission_id
      AND ar.source_receipt_id=r.source_receipt_id AND ar.owner_user_id=NEW.owner_user_id AND ar.turn_id=NEW.turn_id
 WHERE b.acceptance_id=NEW.acceptance_id AND b.owner_user_id=NEW.owner_user_id AND b.turn_id=NEW.turn_id
   AND p.source_receipt_id=r.source_receipt_id AND p.cohort_sha256=b.cohort_sha256
   AND r.binding_kind='admission' AND r.admission_id=b.admission_id
   AND NOT EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events e
                  WHERE e.acceptance_id=b.acceptance_id AND e.event_kind='proof_committed')
)
BEGIN SELECT RAISE(ABORT,'proof is not an uncommitted receipt in this admission batch'); END;

CREATE TABLE p2_v3_metadata_acceptance_events (
    acceptance_id TEXT NOT NULL,
    event_seq INTEGER NOT NULL CHECK(typeof(event_seq)='integer' AND event_seq>=1),
    event_kind TEXT NOT NULL CHECK(event_kind IN('proof_committed','finalized','unknown','postcommit_observation')),
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    reservation_id TEXT,
    terminal_event_id TEXT,
    terminal_charge_kind TEXT CHECK(terminal_charge_kind IS NULL OR terminal_charge_kind IN('settled','unknown')),
    cost_basis TEXT CHECK(cost_basis IS NULL OR cost_basis IN('conservative_cap','unknown_cap')),
    measured_active_us INTEGER CHECK(measured_active_us IS NULL OR (typeof(measured_active_us)='integer' AND measured_active_us>=0)),
    measured_backend_us INTEGER CHECK(measured_backend_us IS NULL OR (typeof(measured_backend_us)='integer' AND measured_backend_us>=0)),
    charged_active_us INTEGER CHECK(charged_active_us IS NULL OR (typeof(charged_active_us)='integer' AND charged_active_us>=0)),
    charged_backend_us INTEGER CHECK(charged_backend_us IS NULL OR (typeof(charged_backend_us)='integer' AND charged_backend_us>=0)),
    observation_outcome TEXT CHECK(observation_outcome IS NULL OR observation_outcome IN('within_cap','overrun','unknown')),
    overrun_active_us INTEGER NOT NULL DEFAULT 0 CHECK(typeof(overrun_active_us)='integer' AND overrun_active_us>=0),
    overrun_backend_us INTEGER NOT NULL DEFAULT 0 CHECK(typeof(overrun_backend_us)='integer' AND overrun_backend_us>=0),
    occurred_at TEXT NOT NULL,
    PRIMARY KEY(acceptance_id,event_seq),
    FOREIGN KEY(acceptance_id,owner_user_id,turn_id)
      REFERENCES p2_v3_metadata_acceptance_batches(acceptance_id,owner_user_id,turn_id) ON DELETE RESTRICT,
    FOREIGN KEY(reservation_id,terminal_charge_kind,owner_user_id,turn_id)
      REFERENCES p2_v3_charge_events(reservation_id,event_kind,owner_user_id,turn_id) ON DELETE RESTRICT,
    CHECK(CASE
      WHEN event_kind='proof_committed' THEN CASE WHEN
        event_seq=1 AND reservation_id IS NULL AND terminal_event_id IS NULL
        AND terminal_charge_kind IS NULL AND cost_basis IS NULL
        AND measured_active_us IS NULL AND measured_backend_us IS NULL
        AND charged_active_us IS NULL AND charged_backend_us IS NULL
        AND observation_outcome IS NULL AND overrun_active_us=0 AND overrun_backend_us=0
        THEN 1 ELSE 0 END
      WHEN event_kind='finalized' THEN CASE WHEN
        event_seq=2 AND reservation_id IS NOT NULL AND terminal_event_id IS NOT NULL
        AND terminal_charge_kind IS 'settled' AND cost_basis IS 'conservative_cap'
        AND measured_active_us IS NOT NULL AND measured_backend_us IS NOT NULL
        AND charged_active_us IS NOT NULL AND charged_backend_us IS NOT NULL
        AND observation_outcome IS NULL AND overrun_active_us=0 AND overrun_backend_us=0
        THEN 1 ELSE 0 END
      WHEN event_kind='unknown' THEN CASE WHEN
        event_seq=2 AND reservation_id IS NOT NULL AND terminal_event_id IS NOT NULL
        AND terminal_charge_kind IS 'unknown' AND cost_basis IS 'unknown_cap'
        AND measured_active_us IS NULL AND measured_backend_us IS NULL
        AND charged_active_us IS NOT NULL AND charged_backend_us IS NOT NULL
        AND observation_outcome IS NULL
        THEN 1 ELSE 0 END
      WHEN event_kind='postcommit_observation' THEN CASE WHEN
        event_seq>=3 AND reservation_id IS NOT NULL AND terminal_event_id IS NOT NULL
        AND terminal_charge_kind IS NOT NULL AND cost_basis IS NULL
        AND charged_active_us IS NULL AND charged_backend_us IS NULL
        AND observation_outcome IS NOT NULL
        AND ((observation_outcome IN('within_cap','overrun') AND measured_active_us IS NOT NULL AND measured_backend_us IS NOT NULL)
          OR (observation_outcome='unknown' AND ((measured_active_us IS NULL AND measured_backend_us IS NULL) OR (measured_active_us IS NOT NULL AND measured_backend_us IS NOT NULL))))
        THEN 1 ELSE 0 END
      ELSE 0 END=1),
    CHECK(measured_active_us IS NULL OR measured_backend_us IS NULL OR measured_backend_us<=measured_active_us)
);

CREATE UNIQUE INDEX p2_v3_ma_one_terminal ON p2_v3_metadata_acceptance_events(acceptance_id)
 WHERE event_kind IN('finalized','unknown');
CREATE UNIQUE INDEX p2_v3_ma_one_proof_commit ON p2_v3_metadata_acceptance_events(acceptance_id)
 WHERE event_kind='proof_committed';

CREATE TRIGGER p2_v3_ma_event_transition
BEFORE INSERT ON p2_v3_metadata_acceptance_events
BEGIN
 SELECT CASE WHEN NEW.event_seq != COALESCE(
   (SELECT MAX(event_seq)+1 FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=NEW.acceptance_id),1)
   THEN RAISE(ABORT,'event sequence is not contiguous') END;
 SELECT CASE WHEN NEW.event_kind!='proof_committed' AND NEW.reservation_id IS NOT
   (SELECT processing_reservation_id FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=NEW.acceptance_id)
   THEN RAISE(ABORT,'event reservation differs from batch') END;
 SELECT CASE WHEN NEW.event_kind='proof_committed' AND (
   (SELECT COUNT(*) FROM p2_v3_metadata_acceptance_proofs WHERE acceptance_id=NEW.acceptance_id)
     != (SELECT proof_count FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=NEW.acceptance_id)
   OR (SELECT MIN(ordinal) FROM p2_v3_metadata_acceptance_proofs WHERE acceptance_id=NEW.acceptance_id) IS NOT 0
   OR (SELECT MAX(ordinal) FROM p2_v3_metadata_acceptance_proofs WHERE acceptance_id=NEW.acceptance_id)
     IS NOT (SELECT proof_count-1 FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=NEW.acceptance_id)
   OR (SELECT COUNT(DISTINCT ordinal) FROM p2_v3_metadata_acceptance_proofs WHERE acceptance_id=NEW.acceptance_id)
     != (SELECT proof_count FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=NEW.acceptance_id)
 ) THEN RAISE(ABORT,'proof set is not exactly contiguous 0..count-1') END;
 SELECT CASE WHEN NEW.event_kind IN('finalized','unknown') AND NOT EXISTS(
   SELECT 1 FROM p2_v3_metadata_acceptance_events e WHERE e.acceptance_id=NEW.acceptance_id
     AND e.event_seq=1 AND e.event_kind='proof_committed')
   THEN RAISE(ABORT,'terminal event requires committed proof set') END;
 SELECT CASE WHEN NEW.event_kind IN('finalized','unknown') AND NOT EXISTS(
   SELECT 1 FROM p2_v3_metadata_acceptance_batches b
   JOIN p2_v3_charge_events r ON r.reservation_id=b.processing_reservation_id
      AND r.owner_user_id=b.owner_user_id AND r.turn_id=b.turn_id
   JOIN p2_v3_charge_events rr ON rr.reservation_id=b.processing_reservation_id
      AND rr.event_id=b.reserved_event_id AND rr.event_kind=b.reserved_event_kind
      AND rr.owner_user_id=b.owner_user_id AND rr.turn_id=b.turn_id
   JOIN p2_v3_turns t ON t.turn_id=b.turn_id AND t.owner_user_id=b.owner_user_id
   WHERE b.acceptance_id=NEW.acceptance_id AND NEW.owner_user_id IS b.owner_user_id AND NEW.turn_id IS b.turn_id
     AND NEW.reservation_id IS b.processing_reservation_id
     AND rr.profile_id='p2.read-paged-prepayment-refund.v3-candidate' AND rr.stage='backend_processing'
     AND rr.generation=b.generation AND rr.claim_epoch=b.claim_epoch AND rr.authority_epoch=b.authority_epoch
     AND rr.context_revision=b.context_revision AND rr.active_limit_us>0 AND rr.backend_limit_us>0
     AND rr.backend_limit_us<=rr.active_limit_us AND rr.response_bytes_limit=0
     AND rr.logical_query_id IS NULL AND rr.query_attempt_id IS NULL AND rr.admission_id IS NULL
     AND rr.source_role IS NULL AND rr.request_digest IS NULL AND rr.prepared_request_sha256 IS NULL
     AND rr.selected_model_key IS NULL AND rr.validated_measurement_sha256 IS NULL
     AND rr.actual_active_us IS NULL AND rr.actual_backend_us IS NULL AND rr.actual_response_bytes IS NULL
     AND rr.overrun_active_us=0 AND rr.overrun_backend_us=0 AND rr.overrun_response_bytes=0 AND rr.raw_body_sha256 IS NULL
     AND r.profile_id IS rr.profile_id AND r.stage IS rr.stage AND r.generation IS rr.generation
     AND r.claim_epoch IS rr.claim_epoch AND r.authority_epoch IS rr.authority_epoch
     AND r.context_revision IS rr.context_revision AND r.active_limit_us IS rr.active_limit_us
     AND r.backend_limit_us IS rr.backend_limit_us AND r.response_bytes_limit IS rr.response_bytes_limit
     AND r.logical_query_id IS rr.logical_query_id AND r.query_attempt_id IS rr.query_attempt_id
     AND r.admission_id IS rr.admission_id AND r.source_role IS rr.source_role AND r.request_digest IS rr.request_digest
     AND r.prepared_request_sha256 IS rr.prepared_request_sha256 AND r.selected_model_key IS rr.selected_model_key
     AND r.validated_measurement_sha256 IS rr.validated_measurement_sha256
     AND r.actual_response_bytes=0 AND r.raw_body_sha256 IS NULL AND r.overrun_response_bytes=0
     AND ((NEW.event_kind='finalized' AND NEW.terminal_charge_kind IS 'settled'
           AND r.event_id IS NEW.terminal_event_id AND r.event_kind='settled'
           AND r.stage='backend_processing' AND r.actual_active_us=rr.active_limit_us AND r.actual_backend_us=rr.backend_limit_us AND r.overrun_active_us=0 AND r.overrun_backend_us=0
           AND r.actual_backend_us=r.backend_limit_us
           AND NEW.charged_active_us=rr.active_limit_us AND NEW.charged_backend_us=rr.backend_limit_us
           AND NEW.measured_active_us<=rr.active_limit_us AND NEW.measured_backend_us<=rr.backend_limit_us
           AND t.lifecycle='active' AND t.generation=b.generation AND t.input_seq=b.input_seq
           AND t.input_digest=b.input_digest AND t.claim_epoch=b.claim_epoch
           AND t.authority_epoch=b.authority_epoch AND t.context_revision=b.context_revision
           AND EXISTS(SELECT 1 FROM p2_v3_turn_execution_pins pin WHERE pin.turn_id=b.turn_id
             AND pin.owner_user_id=b.owner_user_id AND pin.cohort_sha256=b.cohort_sha256))
       OR (NEW.event_kind='unknown' AND NEW.terminal_charge_kind IS 'unknown'
           AND r.event_id IS NEW.terminal_event_id AND r.event_kind='unknown'
           AND r.stage='backend_processing' AND r.actual_active_us=rr.active_limit_us AND r.actual_backend_us=rr.backend_limit_us
           AND r.actual_backend_us=r.backend_limit_us
           AND NEW.charged_active_us=rr.active_limit_us AND NEW.charged_backend_us=rr.backend_limit_us AND NEW.overrun_active_us=r.overrun_active_us AND NEW.overrun_backend_us=r.overrun_backend_us))
 ) THEN RAISE(ABORT,'terminal event lacks matching cap charge and current identity') END;
 SELECT CASE WHEN NEW.event_kind='postcommit_observation' AND NOT EXISTS(
   SELECT 1 FROM p2_v3_metadata_acceptance_events term
   JOIN p2_v3_metadata_acceptance_batches b ON b.acceptance_id=term.acceptance_id
   JOIN p2_v3_charge_events r ON r.reservation_id=b.processing_reservation_id
      AND r.owner_user_id=b.owner_user_id AND r.turn_id=b.turn_id
   JOIN p2_v3_charge_events rr ON rr.reservation_id=b.processing_reservation_id
      AND rr.event_id=b.reserved_event_id AND rr.event_kind=b.reserved_event_kind
      AND rr.owner_user_id=b.owner_user_id AND rr.turn_id=b.turn_id
   WHERE term.acceptance_id=NEW.acceptance_id AND term.event_seq=2
     AND term.event_kind IN('finalized','unknown')
     AND NEW.owner_user_id IS b.owner_user_id AND NEW.turn_id IS b.turn_id
     AND NEW.reservation_id IS b.processing_reservation_id
     AND NEW.terminal_event_id IS term.terminal_event_id
     AND NEW.terminal_charge_kind IS term.terminal_charge_kind
     AND r.event_id IS term.terminal_event_id AND r.event_kind IS term.terminal_charge_kind
     AND r.profile_id IS rr.profile_id AND r.stage IS rr.stage AND r.generation IS rr.generation
     AND r.claim_epoch IS rr.claim_epoch AND r.authority_epoch IS rr.authority_epoch
     AND r.context_revision IS rr.context_revision AND r.active_limit_us IS rr.active_limit_us
     AND r.backend_limit_us IS rr.backend_limit_us AND r.response_bytes_limit IS rr.response_bytes_limit
     AND r.logical_query_id IS rr.logical_query_id AND r.query_attempt_id IS rr.query_attempt_id
     AND r.admission_id IS rr.admission_id AND r.source_role IS rr.source_role AND r.request_digest IS rr.request_digest
     AND r.prepared_request_sha256 IS rr.prepared_request_sha256 AND r.selected_model_key IS rr.selected_model_key
     AND r.validated_measurement_sha256 IS rr.validated_measurement_sha256
     AND rr.generation=b.generation AND rr.claim_epoch=b.claim_epoch AND rr.authority_epoch=b.authority_epoch
     AND rr.context_revision=b.context_revision AND rr.profile_id='p2.read-paged-prepayment-refund.v3-candidate'
     AND rr.stage='backend_processing' AND rr.response_bytes_limit=0
     AND rr.logical_query_id IS NULL AND rr.query_attempt_id IS NULL AND rr.admission_id IS NULL
     AND rr.source_role IS NULL AND rr.request_digest IS NULL AND rr.actual_active_us IS NULL
     AND rr.prepared_request_sha256 IS NULL AND rr.selected_model_key IS NULL AND rr.validated_measurement_sha256 IS NULL
     AND rr.actual_backend_us IS NULL AND rr.actual_response_bytes IS NULL AND rr.raw_body_sha256 IS NULL
     AND rr.overrun_active_us=0 AND rr.overrun_backend_us=0 AND rr.overrun_response_bytes=0
     AND r.actual_response_bytes=0 AND r.raw_body_sha256 IS NULL AND r.overrun_response_bytes=0
     AND r.stage='backend_processing'
     AND ((NEW.measured_active_us IS NULL AND NEW.measured_backend_us IS NULL)
       OR (NEW.measured_active_us IS NOT NULL AND NEW.measured_backend_us IS NOT NULL
         AND NEW.measured_active_us>=MAX(COALESCE(term.measured_active_us,0),COALESCE((SELECT MAX(p.measured_active_us)
              FROM p2_v3_metadata_acceptance_events p WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'),0))
         AND NEW.measured_backend_us>=MAX(COALESCE(term.measured_backend_us,0),COALESCE((SELECT MAX(p.measured_backend_us)
              FROM p2_v3_metadata_acceptance_events p WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'),0))))
     AND (
       (NEW.observation_outcome='within_cap' AND term.event_kind='finalized'
           AND NEW.measured_active_us<=rr.active_limit_us AND NEW.measured_backend_us<=rr.backend_limit_us
        AND COALESCE((SELECT p.observation_outcome FROM p2_v3_metadata_acceptance_events p
             WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'
             ORDER BY p.event_seq DESC LIMIT 1),'within_cap')='within_cap'
        AND NEW.overrun_active_us=COALESCE((SELECT p.overrun_active_us FROM p2_v3_metadata_acceptance_events p
             WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'
             ORDER BY p.event_seq DESC LIMIT 1),0)
        AND NEW.overrun_backend_us=COALESCE((SELECT p.overrun_backend_us FROM p2_v3_metadata_acceptance_events p
             WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'
             ORDER BY p.event_seq DESC LIMIT 1),0))
       OR
       (NEW.observation_outcome='overrun'
        AND (NEW.measured_active_us>rr.active_limit_us OR NEW.measured_backend_us>rr.backend_limit_us)
        AND NEW.overrun_active_us=MAX(COALESCE(term.overrun_active_us,0),
          COALESCE((SELECT MAX(p.overrun_active_us) FROM p2_v3_metadata_acceptance_events p
                   WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'),0),
          MAX(0,NEW.measured_active_us-rr.active_limit_us))
        AND NEW.overrun_backend_us=MAX(COALESCE(term.overrun_backend_us,0),
          COALESCE((SELECT MAX(p.overrun_backend_us) FROM p2_v3_metadata_acceptance_events p
                   WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'),0),
          MAX(0,NEW.measured_backend_us-rr.backend_limit_us))
       )
       OR
       (NEW.observation_outcome='unknown'
        AND ((NEW.measured_active_us IS NULL AND NEW.measured_backend_us IS NULL)
          OR (NEW.measured_active_us IS NOT NULL AND NEW.measured_backend_us IS NOT NULL))
        AND NEW.overrun_active_us=MAX(COALESCE(term.overrun_active_us,0),
          COALESCE((SELECT MAX(p.overrun_active_us) FROM p2_v3_metadata_acceptance_events p
                   WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'),0),
          MAX(0,COALESCE(NEW.measured_active_us,0)-rr.active_limit_us))
        AND NEW.overrun_backend_us=MAX(COALESCE(term.overrun_backend_us,0),
          COALESCE((SELECT MAX(p.overrun_backend_us) FROM p2_v3_metadata_acceptance_events p
                   WHERE p.acceptance_id=NEW.acceptance_id AND p.event_kind='postcommit_observation'),0),
          MAX(0,COALESCE(NEW.measured_backend_us,0)-rr.backend_limit_us))
       )
     )
     AND (term.event_kind!='unknown' OR NEW.observation_outcome IN('unknown','overrun'))
 ) THEN RAISE(ABORT,'observation inconsistent, nonmonotonic, or attempts to revive publication') END;
END;
CREATE TRIGGER p2_v3_ma_proofs_no_update BEFORE UPDATE ON p2_v3_metadata_acceptance_proofs
BEGIN SELECT RAISE(ABORT,'proof links immutable'); END;
CREATE TRIGGER p2_v3_ma_proofs_no_delete BEFORE DELETE ON p2_v3_metadata_acceptance_proofs
BEGIN SELECT RAISE(ABORT,'proof links immutable'); END;
CREATE TRIGGER p2_v3_ma_proofs_after_commit BEFORE INSERT ON p2_v3_metadata_acceptance_proofs
WHEN EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events e WHERE e.acceptance_id=NEW.acceptance_id AND e.event_kind='proof_committed')
BEGIN SELECT RAISE(ABORT,'proof set is frozen'); END;
CREATE TRIGGER p2_v3_ma_batch_no_update BEFORE UPDATE ON p2_v3_metadata_acceptance_batches
BEGIN SELECT RAISE(ABORT,'acceptance batch immutable'); END;
CREATE TRIGGER p2_v3_ma_batch_no_delete BEFORE DELETE ON p2_v3_metadata_acceptance_batches
BEGIN SELECT RAISE(ABORT,'acceptance batch immutable'); END;
CREATE TRIGGER p2_v3_ma_events_no_update BEFORE UPDATE ON p2_v3_metadata_acceptance_events
BEGIN SELECT RAISE(ABORT,'acceptance events append-only'); END;
CREATE TRIGGER p2_v3_ma_events_no_delete BEFORE DELETE ON p2_v3_metadata_acceptance_events
BEGIN SELECT RAISE(ABORT,'acceptance events append-only'); END;

CREATE TABLE p2_v3_output_metadata_acceptances (
    protected_output_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 128),
    acceptance_id TEXT NOT NULL,
    PRIMARY KEY(protected_output_id,ordinal),
    UNIQUE(protected_output_id,acceptance_id),
    FOREIGN KEY(protected_output_id,owner_user_id,turn_id)
      REFERENCES p2_v3_protected_outputs(protected_output_id,owner_user_id,turn_id) ON DELETE RESTRICT,
    FOREIGN KEY(acceptance_id,owner_user_id,turn_id)
      REFERENCES p2_v3_metadata_acceptance_batches(acceptance_id,owner_user_id,turn_id) ON DELETE RESTRICT
);
CREATE TRIGGER p2_v3_output_metadata_acceptance_gate
BEFORE INSERT ON p2_v3_output_metadata_acceptances
WHEN NOT EXISTS(
 SELECT 1 FROM p2_v3_metadata_acceptance_batches b
 JOIN p2_v3_protected_outputs o ON o.protected_output_id=NEW.protected_output_id
      AND o.owner_user_id=NEW.owner_user_id AND o.turn_id=NEW.turn_id
 JOIN p2_v3_turns t ON t.turn_id=b.turn_id AND t.owner_user_id=b.owner_user_id
 JOIN p2_v3_turn_execution_pins pin ON pin.turn_id=b.turn_id AND pin.owner_user_id=b.owner_user_id
 WHERE b.acceptance_id=NEW.acceptance_id AND b.owner_user_id=NEW.owner_user_id AND b.turn_id=NEW.turn_id
   AND b.cohort_sha256=o.cohort_sha256 AND b.generation=o.generation AND b.input_seq=o.input_seq
   AND b.input_digest=o.input_digest AND b.context_revision=o.context_revision
   AND b.cohort_sha256=pin.cohort_sha256 AND t.lifecycle='active'
   AND t.generation=b.generation AND t.input_seq=b.input_seq AND t.input_digest=b.input_digest
   AND t.claim_epoch=b.claim_epoch AND t.authority_epoch=b.authority_epoch AND t.context_revision=b.context_revision
   AND EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events f
        WHERE f.acceptance_id=b.acceptance_id AND f.event_seq=2 AND f.event_kind='finalized')
   AND EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events obs
        WHERE obs.acceptance_id=b.acceptance_id AND obs.event_kind='postcommit_observation'
          AND obs.observation_outcome='within_cap'
          AND obs.event_seq=(SELECT MAX(x.event_seq) FROM p2_v3_metadata_acceptance_events x
             WHERE x.acceptance_id=b.acceptance_id AND x.event_kind='postcommit_observation'))
)
BEGIN SELECT RAISE(ABORT,'output acceptance lacks current finalized within-cap batch'); END;
CREATE TRIGGER p2_v3_output_acceptances_no_update BEFORE UPDATE ON p2_v3_output_metadata_acceptances
BEGIN SELECT RAISE(ABORT,'output acceptance immutable'); END;
CREATE TRIGGER p2_v3_output_acceptances_no_delete BEFORE DELETE ON p2_v3_output_metadata_acceptances
BEGIN SELECT RAISE(ABORT,'output acceptance immutable'); END;

CREATE TRIGGER p2_v3_output_metadata_link_acceptance_gate
BEFORE INSERT ON p2_v3_output_metadata_links
WHEN NOT EXISTS(
 SELECT 1 FROM p2_v3_metadata_acceptance_proofs ap
 JOIN p2_v3_metadata_acceptance_batches b ON b.acceptance_id=ap.acceptance_id
      AND b.owner_user_id=ap.owner_user_id AND b.turn_id=ap.turn_id
 JOIN p2_v3_output_metadata_acceptances oa ON oa.acceptance_id=b.acceptance_id
      AND oa.protected_output_id=NEW.protected_output_id AND oa.owner_user_id=NEW.owner_user_id AND oa.turn_id=NEW.turn_id
 JOIN p2_v3_protected_outputs o ON o.protected_output_id=NEW.protected_output_id
      AND o.owner_user_id=NEW.owner_user_id AND o.turn_id=NEW.turn_id
 JOIN p2_v3_turns t ON t.turn_id=b.turn_id AND t.owner_user_id=b.owner_user_id
 WHERE ap.metadata_proof_id=NEW.metadata_proof_id AND ap.owner_user_id=NEW.owner_user_id AND ap.turn_id=NEW.turn_id
   AND b.cohort_sha256=o.cohort_sha256 AND b.generation=o.generation AND b.input_seq=o.input_seq
   AND b.input_digest=o.input_digest AND b.context_revision=o.context_revision
   AND t.lifecycle='active' AND t.generation=b.generation AND t.input_seq=b.input_seq
   AND t.input_digest=b.input_digest AND t.claim_epoch=b.claim_epoch
   AND t.authority_epoch=b.authority_epoch AND t.context_revision=b.context_revision
   AND EXISTS(SELECT 1 FROM p2_v3_turn_execution_pins pin WHERE pin.turn_id=b.turn_id
       AND pin.owner_user_id=b.owner_user_id AND pin.cohort_sha256=b.cohort_sha256)
   AND EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events f
       WHERE f.acceptance_id=b.acceptance_id AND f.event_seq=2 AND f.event_kind='finalized')
   AND EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events obs
       WHERE obs.acceptance_id=b.acceptance_id AND obs.event_kind='postcommit_observation'
         AND obs.observation_outcome='within_cap'
         AND obs.event_seq=(SELECT MAX(x.event_seq) FROM p2_v3_metadata_acceptance_events x
             WHERE x.acceptance_id=b.acceptance_id AND x.event_kind='postcommit_observation'))
)
BEGIN SELECT RAISE(ABORT,'metadata link lacks exact accepted proof/current output gate'); END;







