# P2 v3 Store overrun accounting R1

This is a D-only-reviewed candidate Store delta. It changes neither the v3 SQL migration nor any canonical/P1/v2 behavior, and it does not assemble the candidate source backend.

## Budget rule

The existing 003 schema intentionally keeps `p2_v3_turns` summary counters within their original caps. A measured amount above its reservation is stored in the append-only terminal `p2_v3_charge_events.overrun_*` columns, while the summary receives only the reserved/capped amount. Before admitting any later work, the Store now reads the terminal overrun ledger inside the same `BEGIN IMMEDIATE` transaction and computes effective use as:

`capped summary used + still-reserved amount + sum(terminal overrun)`.

This applies independently to active time, backend time, and response bytes. Backend time remains an active-time subset. A known pre-dispatch local operation that ran longer than its reservation retains its measured active overrun. A dispatched operation with measured overrun remains an `unknown` terminal cost event and cannot publish source evidence. Unknown history is audit data, not a permanent ban: remaining budget can still be used if effective consumption leaves room. The next reservation is refused as soon as its requested bound would cross the total cap.

When a dispatched operation's outcome is unknown and no measurements are available, callers may omit all three `actual_*` values. Store conservatively charges the full reservation and records zero measured overrun; it does not treat missing data as measured zero. Partial measured data still requires a valid active-time measurement, with omitted backend/byte measurements defaulting to zero only when the caller actually supplied an active measurement.

The summary snapshot continues to expose the capped counters; it is not a remaining-budget oracle. Reservation admission is authoritative and must be used for every new stage. No overrun amount is re-counted as a model call, repair call, logical read, or GET attempt; those slots are committed once at dispatch as before.

## GET response bound

Each GET reservation is now limited to 1 MiB, while the Turn-wide response budget remains 4 MiB across up to 48 GET attempts. The trusted transport must stop reading at the reservation bound. If a measured response nevertheless exceeds the reservation, Store settles only the reserved amount into the capped summary, records the exact excess as overrun, writes an `unknown` cost event, and clears the raw-body digest. That path is not eligible for wire capture or source acceptance.

The CPU boundary test performs one 1 MiB reservation whose measured size is 1 MiB + 1, then three further GETs of 1 MiB, 1 MiB, and 1 MiB - 1. A second Store instance continues the same live Turn. Effective usage reaches exactly 4 MiB; a following 1-byte reservation is rejected. A single >1 MiB reservation is rejected before it can be dispatched.

## Evidence and limits

`test_p2_v3_store_recovery_edges.py` passes 24 tests in the bounded local CPU run. Two red tests first reproduced the overrun defect: after a known-no-dispatch active overrun, and after a dispatched backend-time overrun, the old code admitted a final 1 µs reservation. A separate red test showed that `unknown` settlement rejected absent actual measurements. The final tests prove overrun-aware refusal, conservative unknown settlement with remaining-budget reuse, exactly-once model/GET slot accounting, and restart through a second Store instance.

This evidence proves Store accounting behavior only. It does not prove a live HTTP transport enforces the byte cap, source parsing/currentness, Auth/RLS, runtime assembly, provider dispatch, or any Supabase/business-database behavior. No SQL migration changed; the prior immutable `final-evidence-r1` remains historical and unmodified.
