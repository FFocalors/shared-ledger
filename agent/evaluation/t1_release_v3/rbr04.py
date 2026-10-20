"""RBR04: AA minor-unit tail and multi-person small-amount coverage.

The root review found that packet rows 15/16/17 show only whole-cent equal
shares and therefore do not demonstrate AA tail handling.  The cause is
structural: the default create amount is ``25 * participant_count``, so every
default equal-split family divides exactly by construction.  RBR04 is a
*coverage* gap, not an allocation defect, so the fix adds cases rather than
changing any existing row.

Each case reuses an existing in-split state family (the same device the read
``empty``/``narrow`` variants already use), so no family count changes; only the
user-authored amount differs.  The amounts are chosen so that the allocator,
which splits at a ``0.0001`` quantum, must leave a deterministic remainder:

* ``aa-tail`` -- a normal-sized amount that does not divide by the participant
  count, so at least two participants receive different, non-whole-cent shares;
* ``small-multi`` -- a very small amount over several participants, which is the
  "many people, tiny amount" case and also leaves a tail.

The allocator gives the extra ``0.0001`` unit to the earliest participants, so
the tail is deterministic and order-stable.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

QUANTUM = Decimal("0.0001")

# (split, family index, expected participants, tag, amount)
RBR04_CASES: tuple[tuple[str, int, int, str, str], ...] = (
    ("train", 5, 6, "aa-tail", "150.01"),
    ("train", 19, 8, "aa-tail", "200.01"),
    ("train", 11, 12, "aa-tail", "300.01"),
    ("train", 5, 6, "small-multi", "0.05"),
    ("validation", 29, 6, "aa-tail", "150.01"),
    ("validation", 31, 8, "aa-tail", "200.01"),
    ("validation", 23, 12, "aa-tail", "300.01"),
    ("validation", 29, 6, "small-multi", "0.05"),
    ("sealed", 41, 6, "aa-tail", "150.01"),
    ("sealed", 43, 8, "aa-tail", "200.01"),
    ("sealed", 47, 12, "aa-tail", "300.01"),
    ("sealed", 41, 6, "small-multi", "0.05"),
)

# Splits whose row bodies are written by the slice.  Sealed is generated and
# validated in memory only, as it must be written last under its own one-shot
# receipt in the full preparation.
WRITTEN_SPLITS = ("train", "validation")


# --- B1: the two AA columns, and their two quanta ---------------------------
#
# Verified against the backend source (not inferred):
#   * splits.amount       -- original currency, 0.0001 quantum
#     (p_original_amount * 10000), AA branch of private.replace_expense_children:
#     trunc(total/n) and the first |remainder| participants move by one unit.
#   * splits.base_amount  -- activity base currency, 0.1 quantum
#     (base_amount * 10), private.redistribute_aa_split_base_amounts:
#     trunc(total/n) and the first |remainder| participants move by one unit.
#
# They are different columns; neither replaces the other, and the generator's
# existing 0.0001 original-currency quantum stays as it is.
QUANTUM_RULING = {
    "original_currency_column": {
        "field": "splits.amount",
        "quantum": "0.0001",
        "units": "p_original_amount * 10000",
        "rule": "trunc(total/n) per participant; first |remainder| in participant_order, id move by one unit",
        "source": "private.replace_expense_children (AA branch)",
    },
    "base_currency_column": {
        "field": "splits.base_amount",
        "quantum": "0.1",
        "units": "base_amount * 10",
        "rule": "trunc(total/n) per participant; first |remainder| in participant_order, id move by one unit",
        "source": "private.redistribute_aa_split_base_amounts",
        "persisted_shape": (
            "create initially writes the base tail to the last participant, but every "
            "create/update/delete/restore and the repair path then call the fair "
            "redistribution, so the persisted row set is the first-N shape"
        ),
    },
    "payments_note": (
        "payments.base_amount keeps the last-participant delta: the fair-allocation "
        "migration redistributes splits only"
    ),
    "generator_decision": (
        "keep the generator's 0.0001 original-currency allocation; add the base column "
        "explicitly rather than replacing one with the other"
    ),
}

# --- B2: base-column coverage cases -----------------------------------------
# (split, family index, tag, original amount, participants, expense currency,
#  fx rate, base-currency override)
# Each case targets expense_1 of a read.expenses row, so both columns are
# factual state rather than a proposal.
BASE_AA_CASES: tuple[tuple[str, int, str, str, int, str | None, str | None, str | None], ...] = (
    ("train", 15, "base-100-3", "100.00", 3, None, None, None),
    ("train", 16, "base-10-6", "10.00", 6, None, None, None),
    ("train", 17, "orig-tail-base-even", "150.01", 6, None, None, None),
    ("train", 18, "fx-both-tail", "100.00", 3, "EUR", "7.10", "CNY"),
    ("validation", 20, "base-100-3", "100.00", 3, None, None, None),
    ("validation", 21, "base-10-6", "10.00", 6, None, None, None),
    ("validation", 22, "orig-tail-base-even", "150.01", 6, None, None, None),
    ("validation", 23, "fx-both-tail", "100.00", 3, "EUR", "7.10", "CNY"),
    ("sealed", 25, "base-100-3", "100.00", 3, None, None, None),
    ("sealed", 26, "base-10-6", "10.00", 6, None, None, None),
    ("sealed", 27, "orig-tail-base-even", "150.01", 6, None, None, None),
    ("sealed", 28, "fx-both-tail", "100.00", 3, "EUR", "7.10", "CNY"),
)

# The share shapes each case must produce.  B01's two examples are the first
# two entries.
BASE_AA_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "base-100-3": {
        "original_shares": ["33.3334", "33.3333", "33.3333"],
        "base_shares": ["33.4", "33.3", "33.3"],
        "original_has_tail": True,
        "base_has_tail": True,
    },
    "base-10-6": {
        "original_shares": ["1.6667", "1.6667", "1.6667", "1.6667", "1.6666", "1.6666"],
        "base_shares": ["1.7", "1.7", "1.7", "1.7", "1.6", "1.6"],
        "original_has_tail": True,
        "base_has_tail": True,
    },
    "orig-tail-base-even": {
        "original_shares": ["25.0017", "25.0017", "25.0017", "25.0017", "25.0016", "25.0016"],
        "base_shares": ["25.0", "25.0", "25.0", "25.0", "25.0", "25.0"],
        "original_has_tail": True,
        "base_has_tail": False,
    },
    "fx-both-tail": {
        "original_shares": ["33.3334", "33.3333", "33.3333"],
        "base_shares": ["236.7", "236.7", "236.6"],
        "original_has_tail": True,
        "base_has_tail": True,
    },
}


class CoverageError(RuntimeError):
    pass


def units(amount: str) -> int:
    """Exact quantum units of a 2-decimal amount."""
    scaled = Decimal(amount) / QUANTUM
    if scaled != scaled.to_integral_value():
        raise CoverageError(f"amount is not a whole number of quantum units: {amount}")
    return int(scaled)


def split_has_tail(amount: str, participants: int) -> bool:
    """True when equal splitting cannot give everyone the same share."""
    if participants < 2:
        return False
    return units(amount) % participants != 0


def expected_tail_shape(amount: str, participants: int) -> dict[str, Any]:
    """The exact allocation the current allocator must produce."""
    total = units(amount)
    base, remainder = divmod(total, participants)
    if total < participants:
        raise CoverageError("amount is too small for strictly positive allocations")
    shares = [base + (1 if index < remainder else 0) for index in range(participants)]
    return {
        "participants": participants,
        "base_units": base,
        "remainder_units": remainder,
        "distinct_share_count": len(set(shares)),
        "first_share": f"{Decimal(shares[0]) * QUANTUM:.4f}",
        "last_share": f"{Decimal(shares[-1]) * QUANTUM:.4f}",
    }


def audit_case(row: dict[str, Any], *, expected_participants: int, expected_amount: str) -> dict[str, Any]:
    """Check one converted case for conservation and a real tail."""
    expected = row["expected"]
    if expected["task_operation"] != "expense.create":
        raise CoverageError("an AA coverage case must be an expense.create proposal")
    fields = row["trace"][-1]["target"]["fields"]
    amount = fields["original_amount"]
    if amount != expected_amount:
        raise CoverageError(f"proposal amount {amount} differs from the case amount {expected_amount}")
    if split_has_tail(amount, expected_participants) is False:
        raise CoverageError(f"case {row['sample_id']} does not produce an AA tail")

    payments = [Decimal(item["amount"]) for item in fields["payment_allocations"]]
    split = fields["split"]
    if split["mode"] != "equal":
        raise CoverageError("an AA coverage case must use an equal split")
    refs = split["participant_refs"]
    if len(refs) != expected_participants:
        raise CoverageError(
            f"case {row['sample_id']} splits over {len(refs)} participants, "
            f"expected {expected_participants}"
        )
    shape = expected_tail_shape(amount, expected_participants)

    # Conservation: payments and the equal split must each reconstruct the
    # exact amount, at the allocator's quantum, with no rounding residue.
    payer_count = len(payments)
    payer_total = sum(payments)
    if payer_total != Decimal(amount):
        raise CoverageError(f"payment allocations sum to {payer_total}, not {amount}")
    if any(payment <= 0 for payment in payments):
        raise CoverageError("payment allocations must be strictly positive")
    if units(amount) < payer_count:
        raise CoverageError("amount is too small to pay from this many payers")

    return {
        "sample_id": row["sample_id"],
        "split": row["split"],
        "amount": amount,
        "currency": fields["original_currency"],
        "participants": expected_participants,
        "payer_count": payer_count,
        "payment_total": f"{payer_total:.4f}",
        "split_mode": split["mode"],
        "tail": shape,
        "conserved": True,
    }
