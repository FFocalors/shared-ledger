# P2 v3 source codec/backend candidate diff (CPU-only)

Status: isolated, default-off candidate. This increment adds a strict source codec and an additive v3 adapter path beside the existing v2 behavior. It does not alter the canonical v1 contract or activate v3 in the runtime. The adapter uses fake transport/budget ports in the tests; it does not establish live Supabase behavior, current authorization, persisted source proof, or model quality.

## Version and source boundary

The candidate uses the already-selected tuple `profile=p2.read-paged-prepayment-refund.v3-candidate`, `api=3.0.0`, `semantic=2.1.0`, `operations=2.1.0`, `trajectory=2.0.0`. No fifth version field was added. The existing canonical/v2 path remains the default; v3 is not registered or assembled with the Runtime, Store, API, provider, or scheduler in this increment.

The source codec parses only bounded, allowlisted tables/columns and projects strict DTOs. It keeps raw amounts as source lexemes while using Decimal numeric comparison for cross-row consistency. Source timestamps must be timezone-aware; the codec converts them to UTC while preserving the represented instant, and does not retain the original offset. A null source `bill_occurred_at` remains null; no timestamp is invented. Activity `updated_at` stays in the private scope snapshot/currentness fence; the public Activity label follows the frozen contract and carries its financial version with no row-updated timestamp. Legacy child scope with no configured child-membership restriction remains available, while configured-empty membership grants no child access. UI expense UUID hints are bounded to 32 unique IDs and remain untrusted until revalidated against current source relationships.

The per-capture-chain cap is 32 source pages. The cumulative Turn limits remain 48 GETs, 1 MiB per response, 4 MiB total response bytes, 20 seconds backend-active time within the 240-second Turn budget; continuation/restart does not reset them. Pages remain bounded to 16 rows, at most four pages/64 rows per table. The CPU suite includes a 17-expense continuation case using 18 GETs per chain; initial admission plus two chains costs 42 GETs, under the same 48-GET Turn cap.

Date filters currently compare the UTC calendar date after source timestamps are converted to UTC. This is not a user-local “today” interpretation; timestamp instants are preserved, but original offsets are not retained. No user-local calendar behavior is claimed.

## R4 nullable bill-time correction

The only contract edit in R4 is the `PrepaymentUsageFact.bill_occurred_at` validator: `None` is preserved, while non-null values still pass the existing aware-datetime validator. Other required timestamps and the frozen exported v3 schema remain unchanged. The regenerated candidate schema is byte-for-byte identical to the frozen R3 schema at 128,558 bytes, SHA-256 `a52503a281057ad3301f6e6bd16945f7d3f1d863c550ccf318a0bbe8d2d49981`.

## CPU evidence

At `2026-10-15T03:33:36.2959896Z`–`2026-10-15T03:33:38.3260352Z`, Python 3.12.0 ran the existing v3 contract tests and the new source/backend tests together: 51 passed in 0.93 seconds, exit 0 (34 contract cases and 17 source/backend cases). The source tests include strict JSON `null` round-trip, aware bill-time round-trip, and negative checks on the actual required `ExpenseFact.occurred_at` field for null/naive values. Fixtures are synthetic and use fake transport/budget ports. Schema generation is a local import/serialization check only. Earlier WIP failures, the first strict-aware fixture failure, and the schema-check attempt with an incorrect `PYTHONPATH` are retained in the D evidence package; they are not hidden or counted as current passes.

## Explicit non-claims and next seam

This candidate does not write Store source-acceptance receipts or QEV proofs. The existing Store capture path remains cost-only; hashes supplied by an adapter are not source truth. A future Store acceptance seam must bind the exact transient captured response bytes, response metadata, strict parsed DTO digest, and authorized query/attempt, without persisting bearer tokens, raw HTTP bodies, or continuation secrets. No Supabase project, SDK, network, database, Docker, model, training/evaluation, or T1 dataset was accessed in this increment.

Root directions bound to this work: source codec/backend implementation R1 SHA-256 `9f6dc1cd0518e25721f2e2fa02ede41325a1d4cb35f0eb67135f0df92f887c17`; source budget correction R2 SHA-256 `2a8ce062740cea5a3b09609e95c1c9e37968027f1fe3d1f34716d974005cfaa6`; R3 SHA-256 `166a135f769cca91424b5461e3872f90b4fd6c3cc62590f97f1e728f3896feec`; nullable bill-time R4 SHA-256 `28e8a20ffd69af8c62410b98e6bd79ec96780e90c00b02590a927c6ccf19b744`.

