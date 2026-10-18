DROP TRIGGER p2_v3_chain_reservation_matches_charge;

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
                    (NEW.source_table='activities' AND NEW.source_role IN ('activity','financial_version','scope_label')) OR
                    (NEW.source_table='activity_members' AND NEW.source_role='membership') OR
                    (NEW.source_table='participants' AND NEW.source_role IN ('participant','scope_label')) OR
                    (NEW.source_table='ledger_units' AND NEW.source_role IN ('ledger_unit','scope_label')) OR
                    (NEW.source_table='sub_activity_participants' AND NEW.source_role='ledger_unit') OR
                    (NEW.source_table='participant_claims' AND NEW.source_role='actor') OR
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
