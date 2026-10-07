# Current prepayment eligibility rule (2026-10-06)

This dated addendum records the current product rule for verification, runtime
guidance, and future dataset curation. It does not rewrite or re-version the
frozen AI model contract, business-logic version 1.2 validator, canonical
training manifests, training reports, or generated historical data.

Prepayment preview, creation, return, automatic usage, and final-settlement
prepayment-return paths apply only to `large` Activities. Ordinary Activities
have no prepayment entry point and must reject preview/create/return requests
with SQLSTATE `23514` and the message `普通活动不支持预存`. A mixed request is
rejected as a whole; its debt-settlement portion is not converted into a normal
settlement transfer. Ordinary bilateral final settlement remains supported.

In large Activities, the prepayment account remains Activity-level. Expenses
and linked refunds are recorded in a valid `sub_activity` ledger; prepayment
itself is not assigned to a sub-activity.

Frozen synthetic datasets may contain ordinary-Activity prepayment positives
from the former rule; they are not evidence of persisted application history.
Keep those files intact for reproducibility, but mark those rows ineligible as
positives under the current rule. No production history conversion or
compatibility path is needed. Future current-rule samples must use large
Activities and valid sub-activity ledgers where an expense is present.
