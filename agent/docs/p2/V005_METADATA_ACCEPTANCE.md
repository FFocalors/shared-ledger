# V005 metadata acceptance migration candidate

p2_v3_metadata_acceptance_migration.sql is the byte-for-byte repository copy of the reviewed D-only V005 R2 candidate.

- Source package: D:\AI\runs\shared-ledger\p2\metadata-acceptance-v005-candidate-r2-20261015T2343Z-luna\005_metadata_acceptance_r2.sql
- Source SHA-256: 87fc05ed40c7cf68c6483be4d448f92b72dce44a122cd7cd6916200b9fc7f32e
- Source and destination size: 28,867 bytes
- Root-recorded limited review receipt SHA-256: bbc6bca60fbb700df300ee7f994d109988570b94d2a8ada3b1a86a5d2a03448b. The receipt file itself was not present in the source candidate package at copy time.

The isolated D-only test receipt reports 25 SQLite CPU constraint tests passing against fresh local databases with migrations 001–004 followed by this candidate. That evidence covers SQL constraint behavior only. It does not establish Store integration, source authenticity, Auth/RLS, Runtime publication, or a bounded commit time.

V005 records conservative reservation caps separately from elapsed measurements; a reserved cap is not a measured duration. A future Store must choose a metadata-processing cap supported by separate budget evidence and smaller than the remaining overall backend/Turn allowance. It must preserve the existing cumulative budget limits.

Migrations 001–004 are unchanged. This file is not wired into the migration loader, and no Store acceptance/publisher, post-C same-worker permit, recovery gate, or Runtime publication rule is implemented by this copy. Existing V004 proofs are not implicitly finalized. Treat the migration as an unassembled candidate pending review and separate Store integration.

