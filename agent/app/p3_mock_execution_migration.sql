-- P3a mock write path: a durable, exactly-once mock business ledger.
--
-- This is NOT the real business database. It stands in for "the effect happened
-- outside the agent" so the agent's write path can be exercised without any
-- business write: an effect row keyed by the deterministic execution id, and a
-- per-activity financial version that a preview binds and a confirmation
-- re-checks.
--
-- `mock_execution_ledger.execution_id` is the primary key, and
-- `(proposal_id, proposal_revision)` is unique. Together they make a second
-- application of the same confirmation impossible at the storage level, even if
-- a retry arrived with a different client request id or a different derived id.

CREATE TABLE mock_ledger_state (
    activity_id TEXT PRIMARY KEY,
    financial_version INTEGER NOT NULL CHECK (financial_version >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE mock_execution_ledger (
    execution_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    proposal_revision INTEGER NOT NULL CHECK (proposal_revision >= 1),
    operation TEXT NOT NULL,
    command_sha256 TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    effect_json TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE UNIQUE INDEX mock_execution_ledger_proposal_revision
    ON mock_execution_ledger(proposal_id, proposal_revision);

CREATE INDEX mock_execution_ledger_owner
    ON mock_execution_ledger(owner_user_id, applied_at);
