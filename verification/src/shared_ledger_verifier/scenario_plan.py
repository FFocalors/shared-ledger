"""Reproducible, seed-driven ScenarioPlan objects that aim generation at a focus.

Raising the generator's sampling temperature produces *unreliable* variety: the
model may still emit the same shape, and the same seed would not reproduce the
same case.  A ScenarioPlan instead decides the business shape up front --
participants, who pays what, the exact amounts, and the operation sequence --
from a seed, and then hands that decision to the model as facts it must encode.

Two properties matter:

* ``plan_for(focus, seed)`` is a pure function of its arguments, so the same
  seed always yields the same plan and therefore the same business inputs.
* Different seeds pick different plan dimensions, so the batch actually walks
  the variation space instead of repeating one scenario.

The plan is advisory to the model but authoritative for the focus contract: the
plan is constructed so that a scenario which faithfully encodes it passes
``check_focus``.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from decimal import Decimal

from .focus_contract import (
    AMOUNT_PATTERNS,
    EDGE_TAGS,
    PARTICIPANT_NAMES,
    FocusDefinitionError,
    focus_spec,
)

# Amount vocabularies per pattern.  Every value has at most one fractional
# digit, which is the Loader's limit for amounts in the activity base currency.
_AMOUNT_TABLE: dict[str, tuple[str, ...]] = {
    "divisible": ("30.0", "60.0", "90.0", "120.0", "150.0", "300.0"),
    "non_divisible": ("10.0", "20.0", "40.0", "70.0", "100.0", "110.0"),
    "decimal": ("7.7", "12.3", "33.3", "66.6", "99.9"),
    "large": ("5000.1", "8888.8", "9999.9", "12345.6"),
    "small": ("0.3", "0.9", "1.2", "3.3"),
}


def _one_decimal(value: Decimal) -> str:
    """Render a Decimal as a decimal string with at most one fractional digit."""
    return format(value.quantize(Decimal("0.1")), "f")


def _fmt(value: Decimal, scale: int) -> str:
    """Render a Decimal with exactly ``scale`` fractional digits."""
    return format(value.quantize(Decimal(1).scaleb(-scale)), "f")


_MULTI_REPAYMENT_MIN_TENTHS = 4


def _tenths(value: Decimal) -> int:
    return int((value * 10).to_integral_value())


@dataclass(frozen=True)
class ScenarioPlan:
    """A concrete, reproducible business shape for one generated case."""

    seed: int
    focus: str
    participant_count: int
    payer_count: int
    amount_pattern: str
    operation_count: int
    edge_tags: tuple[str, ...]
    currency: str
    participants: tuple[str, ...]
    amounts: tuple[str, ...]
    steps: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def fingerprint(self) -> str:
        """Stable identity of the plan, independent of seed numbering."""
        material = json.dumps(
            {
                "focus": self.focus,
                "participants": list(self.participants),
                "amounts": list(self.amounts),
                "steps": list(self.steps),
                "edge_tags": list(self.edge_tags),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _rng(focus: str, seed: int) -> random.Random:
    digest = hashlib.sha256(f"{focus}:{seed}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _partition(total: Decimal, count: int, rng: random.Random, scale: int = 1) -> list[Decimal]:
    """Split ``total`` into ``count`` strictly positive parts of ``scale`` digits."""
    step = Decimal(1).scaleb(-scale)
    units = int((total / step).to_integral_value())
    if units < count:
        raise FocusDefinitionError(f"amount {total} is too small to split {count} ways")
    cuts = sorted(rng.sample(range(1, units), count - 1))
    edges = [0, *cuts, units]
    return [Decimal(edges[i + 1] - edges[i]) * step for i in range(count)]


def _distinct_partition(total: Decimal, count: int, rng: random.Random) -> list[Decimal]:
    """Like :func:`_partition` but retries until the parts are not all equal."""
    for _ in range(12):
        parts = _partition(total, count, rng)
        if len(set(parts)) > 1:
            return parts
    return parts


def _debt_pair(amount: Decimal, rng: random.Random) -> tuple[Decimal, Decimal]:
    """Split a total into (what the debtor bears, what the creditor bears), both positive."""
    for _ in range(8):
        parts = _partition(amount, 2, rng)
        if parts[0] > 0 and parts[1] > 0:
            return parts[0], parts[1]
    half = Decimal(_one_decimal(amount / 2))
    return half, Decimal(_one_decimal(amount - half))


def _partial(debt: Decimal, rng: random.Random, scale: int = 1) -> Decimal:
    """Pick an amount strictly between zero and ``debt`` at the given scale."""
    step = Decimal(1).scaleb(-scale)
    if debt <= step:
        return debt
    parts = _partition(debt, 2, rng, scale)
    return min(parts) if min(parts) > 0 else debt


def _pick_amount(pattern: str, participant_count: int, rng: random.Random) -> Decimal:
    """Choose a total that honours the requested amount pattern."""
    if pattern == "divisible":
        # A whole multiple of the participant count, so an equal split is exact.
        step = Decimal(rng.choice(("10.0", "20.0", "30.0")))
        return step * participant_count
    if pattern == "non_divisible":
        candidates = [Decimal(value) for value in _AMOUNT_TABLE["non_divisible"]]
        usable = [value for value in candidates if _tenths(value) % participant_count != 0]
        if usable:
            return rng.choice(usable)
        # No one-decimal total divides unevenly by this count (4 and 5 never do),
        # so fall back to a divisible total and let the contract report the shape.
        return Decimal(rng.choice(_AMOUNT_TABLE["divisible"]))
    return Decimal(rng.choice(_AMOUNT_TABLE[pattern]))


def _payer_count(focus: str, spec_payers: tuple[int, ...], participant_count: int,
                 rng: random.Random) -> int:
    """Choose how many participants pay, always leaving at least one pure debtor."""
    usable = [count for count in spec_payers if 1 <= count < participant_count]
    if not usable:
        usable = [1]
    return rng.choice(usable)


def plan_for(focus: str, seed: int) -> ScenarioPlan:
    """Derive one ScenarioPlan.  Pure function of ``(focus, seed)``."""
    spec = focus_spec(focus)
    rng = _rng(focus, seed)
    low, high = spec.participants
    participant_count = rng.randint(low, high)
    if focus == "aa_rounding":
        # A one-decimal CNY amount can only divide unevenly by 3.
        participant_count = 3
    payer_count = _payer_count(focus, spec.payers, participant_count, rng)
    amount_pattern = rng.choice(spec.amount_patterns)
    participants = PARTICIPANT_NAMES[:participant_count]
    amount = _pick_amount(amount_pattern, participant_count, rng)
    if focus == "multiple_repayments" and _tenths(amount) < _MULTI_REPAYMENT_MIN_TENTHS:
        # Two positive instalments need two tenths, and a partial plan needs a
        # third left over; a smaller total cannot express the focus at all.
        amount = Decimal("0.4")
    edge_tags = _realisable_tags(
        rng.sample(spec.edge_tags, min(2, len(spec.edge_tags))), amount, participant_count
    )
    steps, amounts = _build_steps(
        focus, participants, payer_count, amount, amount_pattern, edge_tags, rng,
        scale=spec.plan_amount_scale,
    )
    # Every branch may hand back Decimals; the plan stores plain decimal strings.
    normalized = tuple(
        value if isinstance(value, str) else _fmt(Decimal(value), spec.plan_amount_scale)
        for value in amounts
    )
    plan = ScenarioPlan(
        seed=seed,
        focus=focus,
        participant_count=participant_count,
        payer_count=payer_count,
        amount_pattern=amount_pattern,
        operation_count=len(steps),
        edge_tags=edge_tags,
        currency=spec.plan_currency,
        participants=participants,
        amounts=normalized,
        steps=tuple(steps),
    )
    inconsistency = check_plan(plan)
    if inconsistency is not None:
        raise FocusDefinitionError(f"plan for {focus} seed {seed} is inconsistent: {inconsistency}")
    return plan


def check_plan(plan: ScenarioPlan) -> str | None:
    """Verify a plan honours its focus spec.  Returns a reason, or None when fine.

    This runs inside :func:`plan_for`, so an unsatisfiable plan can never reach
    the model: the batch would fail loudly at planning time instead of spending
    a generation request on a case that cannot satisfy its contract.
    """
    spec = focus_spec(plan.focus)
    low, high = spec.participants
    if not low <= plan.participant_count <= high:
        return f"{plan.participant_count} participants is outside {low}-{high}"
    if len(plan.participants) != plan.participant_count:
        return "participant roster length does not match participant_count"
    if plan.payer_count not in spec.payers:
        return f"payer_count {plan.payer_count} is not in {spec.payers}"
    if plan.payer_count >= plan.participant_count:
        return "payer_count leaves no pure debtor"
    if plan.amount_pattern not in spec.amount_patterns:
        return f"amount_pattern {plan.amount_pattern} is not in {spec.amount_patterns}"
    if plan.amount_pattern not in AMOUNT_PATTERNS:
        return f"unknown amount_pattern {plan.amount_pattern}"
    if plan.operation_count not in spec.operation_counts:
        return f"operation_count {plan.operation_count} is not in {spec.operation_counts}"
    if len(plan.steps) != plan.operation_count:
        return "step count does not match operation_count"
    if plan.currency != spec.plan_currency:
        return f"plan currency {plan.currency} does not match the focus currency {spec.plan_currency}"
    unknown_tags = set(plan.edge_tags) - set(spec.edge_tags)
    if unknown_tags:
        return f"edge tags {sorted(unknown_tags)} are not declared by the focus"
    for amount in plan.amounts:
        try:
            value = Decimal(amount)
        except Exception:
            return f"amount {amount!r} is not a decimal string"
        if max(0, -value.as_tuple().exponent) > spec.plan_amount_scale:
            return (
                f"amount {amount!r} has more than {spec.plan_amount_scale} fractional digit(s)"
            )
    if plan.focus == "aa_rounding":
        first = Decimal(plan.amounts[0])
        if not _residual_exists(first, plan.participant_count):
            return f"amount {first} divides exactly by {plan.participant_count}"
    if "rounding_residual" in plan.edge_tags:
        first = Decimal(plan.amounts[0])
        if not _residual_exists(first, plan.participant_count):
            return f"edge tag rounding_residual is not realised by amount {first}"
    return None


def _realisable_tags(tags: list[str], amount: Decimal, participant_count: int) -> tuple[str, ...]:
    """Drop edge tags the chosen amount cannot actually realise.

    Tags are drawn before the amount is known, so a divisible total would
    otherwise advertise ``rounding_residual``. The tag list must describe the
    plan that was built, not one that was considered.
    """
    kept = [
        tag for tag in tags
        if tag != "rounding_residual" or _residual_exists(amount, participant_count)
    ]
    return tuple(sorted(set(kept)))


def _residual_exists(amount: Decimal, count: int) -> bool:
    if count <= 0:
        return False
    return int((abs(amount) * Decimal(10_000)).to_integral_value()) % count != 0


def _build_steps(
    focus: str,
    participants: tuple[str, ...],
    payer_count: int,
    amount: Decimal,
    amount_pattern: str,
    edge_tags: tuple[str, ...],
    rng: random.Random,
    scale: int = 1,
) -> tuple[list[str], list[str]]:
    """Return (operation steps, the amounts those steps use).

    Every branch states concrete numbers and actors so that the raw-case model
    and the Compiler both encode the same facts.
    """
    total = _fmt(amount, scale)
    others = list(participants[1:])
    payer_names = participants[:payer_count]
    if payer_count >= len(participants):
        payer_names = participants[:-1]  # keep at least one pure debtor
    payments = _partition(amount, len(payer_names), rng)
    payment_text = ", ".join(
        f"{name} pays {_one_decimal(value)}" for name, value in zip(payer_names, payments)
    )

    if focus in {"expense_aa", "single_payer_aa", "multi_payer_aa", "aa_rounding"}:
        aa = ", ".join(participants)
        step = (
            f"1. create_expense: amount {total} CNY, split_method aa over all participants "
            f"[{aa}], with {payment_text} — payments must sum exactly to {total}."
        )
        return [step], [total, *[_one_decimal(value) for value in payments]]

    if focus == "manual_split":
        creditors = list(participants[: max(1, payer_count)])
        bearers = list(participants[1:]) or list(participants)
        bearer_count = max(2, min(len(bearers), 1 + payer_count))
        bearers = bearers[:bearer_count]
        shares = _distinct_partition(amount, len(bearers), rng)
        share_text = ", ".join(
            f"{name} bears {_one_decimal(value)}" for name, value in zip(bearers, shares)
        )
        step = (
            f"1. create_expense: amount {total} CNY, split_method manual with splits "
            f"{share_text}. Payments: {payment_text}. Both payments and splits must sum "
            f"exactly to {total}."
        )
        return [step], [total, *[_one_decimal(v) for v in payments], *[_one_decimal(v) for v in shares]]

    if focus in {"fifo_repayment", "targeted_repayment", "multiple_repayments"}:
        creditor, debtor = participants[0], participants[1]
        debt, rest = _debt_pair(amount, rng)
        if focus == "multiple_repayments":
            # `plan_for` guarantees enough tenths; give the debtor the larger
            # share when the random split left too little for the instalments.
            needed = 2 if "full_settlement" in edge_tags else 3
            if _tenths(debt) < needed:
                debt = Decimal(_one_decimal(amount - Decimal("0.1")))
                rest = Decimal(_one_decimal(amount)) - debt
        steps = [
            f"1. create_expense: amount {total} CNY, split_method manual, {creditor} pays {total}, "
            f"splits {{ {debtor}: {_one_decimal(debt)}, {creditor}: {_one_decimal(rest)} }} so "
            f"{debtor} owes {creditor} exactly {_one_decimal(debt)}."
        ]
        used = [total, _one_decimal(debt), _one_decimal(rest)]
        if focus == "multiple_repayments":
            units = _tenths(debt)
            # The contract needs at least two instalments; a "partial" plan needs a
            # third tenth left over so the instalments do not settle the whole debt.
            settle_all = "full_settlement" in edge_tags or units < 3
            instalments = _partition(debt, 3, rng)[:2] if not settle_all else _partition(
                debt, 3 if units >= 3 else 2, rng
            )
            for index, value in enumerate(instalments, start=2):
                steps.append(
                    f"{index}. fifo_repayment: {debtor} repays {creditor} {_one_decimal(value)} CNY "
                    f"with no target expense, as one instalment of a multi-instalment repayment."
                )
                used.append(_one_decimal(value))
            settled = sum(instalments, Decimal(0))
            steps[-1] += (
                f" Together the instalments settle the whole {_one_decimal(debt)} CNY debt."
                if settled >= debt
                else f" The instalments leave {_one_decimal(debt - settled)} CNY of the debt outstanding."
            )
            return steps, used

        settle = "full_settlement" in edge_tags
        portion = debt if settle else _partial(debt, rng)
        mode = "targeted_repayment" if focus == "targeted_repayment" else "fifo_repayment"
        target = ", target_expense_refs [expense_1]" if mode == "targeted_repayment" else ""
        note = (
            "This settles the debt completely."
            if portion >= debt
            else f"This is strictly partial: {_one_decimal(debt - portion)} CNY stays outstanding."
        )
        steps.append(
            f"2. {mode}: {debtor} repays {creditor} exactly {_one_decimal(portion)} CNY{target}. {note}"
        )
        used.append(_one_decimal(portion))
        return steps, used

    if focus in {"prepayment_before_debt", "prepayment_after_debt"}:
        owner, custodian = participants[0], participants[1]
        third = participants[2:]
        debt, rest = _debt_pair(amount, rng)
        prepay = Decimal(_one_decimal(amount))
        prepay_step = (
            f"create_prepayment: owner {owner} pays {prepay} CNY to custodian {custodian}, "
            f"creating a prepayment account owned by {owner}."
        )
        expense_step = (
            f"create_expense: amount {total} CNY, split_method manual, {custodian} pays {total}, "
            f"splits {{ {owner}: {_one_decimal(debt)}, {custodian}: {_one_decimal(rest)} }}"
            + (f"; {', '.join(third)} bear nothing" if third else "")
            + f". This makes {owner} owe {custodian} exactly {_one_decimal(debt)}."
        )
        if focus == "prepayment_before_debt":
            steps = [f"1. {prepay_step}", f"2. {expense_step}"]
        else:
            steps = [f"1. {expense_step}", f"2. {prepay_step}"]
        return steps, [prepay, total, _one_decimal(debt), _one_decimal(rest)]

    if focus == "prepayment_return":
        owner, custodian = participants[0], participants[1]
        prepay = Decimal(_one_decimal(amount))
        back = Decimal(_one_decimal(max(Decimal("0.1"), prepay / 2)))
        steps = [
            f"1. create_prepayment: owner {owner} pays {prepay} CNY to custodian {custodian}.",
            f"2. return_prepayment: custodian {custodian} returns {back} CNY to owner {owner} "
            f"from that same prepayment account.",
        ]
        return steps, [prepay, back]

    if focus in {"linked_refund", "prepayment_refund"}:
        creditor, debtor = participants[0], participants[1]
        steps: list[str] = []
        used: list[str] = []
        if focus == "prepayment_refund":
            owner, custodian = participants[0], participants[1]
            prepay = Decimal(_one_decimal(amount))
            steps.append(
                f"1. create_prepayment: owner {owner} pays {prepay} CNY to custodian {custodian}."
            )
            used.append(prepay)
            payer, bearer = custodian, participants[2] if len(participants) > 2 else owner
            share = Decimal(_one_decimal(amount))
            other = Decimal(_one_decimal(amount - share))
            steps.append(
                f"2. create_expense: amount {total} CNY, split_method manual, {payer} pays {total}, "
                f"splits {{ {bearer}: {_one_decimal(share)}, {payer}: {_one_decimal(other)} }}."
            )
            used.extend([total, _one_decimal(share), _one_decimal(other)])
            expense_index = 2
        else:
            share = Decimal(_one_decimal(amount))
            steps.append(
                f"1. create_expense: amount {total} CNY, split_method manual, {creditor} pays "
                f"{total}, splits {{ {debtor}: {_one_decimal(share)} }}."
            )
            used.extend([total, _one_decimal(share)])
            expense_index = 1
        refund = Decimal(_one_decimal(max(Decimal("0.1"), Decimal(_one_decimal(amount)) / 2)))
        receiver = participants[0]
        beneficiary = participants[2] if len(participants) > 2 else participants[1]
        if receiver == beneficiary:
            beneficiary = participants[1]
        steps.append(
            f"{expense_index + 1}. linked_refund of expense_{expense_index}: amount "
            f"-{_one_decimal(refund)} CNY, original_expense_ref expense_{expense_index}. "
            f"The refund is RECEIVED by {receiver} and BENEFITS {beneficiary} — these two "
            f"participants must be different. Its payments and manual splits are negative and "
            f"each sum to exactly -{_one_decimal(refund)}."
        )
        used.append(_one_decimal(refund))
        return steps, used

    if focus == "negative_expense":
        payer, bearer = participants[0], participants[1]
        steps = [
            f"1. create_expense: amount -{total} CNY (a negative adjustment, NOT a linked "
            f"refund, so it has no original_expense_ref), split_method manual, {payer} pays "
            f"-{total}, splits {{ {bearer}: -{total} }}."
        ]
        return steps, [total]

    if focus == "void_transfer":
        creditor, debtor = participants[0], participants[1]
        debt = Decimal(_one_decimal(_partition(amount, 2, rng)[0]))
        rest = Decimal(_one_decimal(amount - debt))
        if debt <= 0 or rest <= 0:
            debt, rest = Decimal("10.0"), Decimal(_one_decimal(amount - Decimal("10.0")))
        steps = [
            f"1. create_expense: amount {total} CNY, split_method manual, {creditor} pays {total}, "
            f"splits {{ {debtor}: {_one_decimal(debt)}, {creditor}: {_one_decimal(rest)} }} so "
            f"{debtor} owes {creditor} {_one_decimal(debt)}.",
            f"2. fifo_repayment: {debtor} repays {creditor} {_one_decimal(debt)} CNY, settling the "
            f"debt and recording a real transfer.",
            "3. void_transfer: void the transfer created by step 2, with a short reason. The "
            "repayment history stays recorded but its current financial effect is removed.",
        ]
        return steps, [total, _one_decimal(debt), _one_decimal(rest)]

    if focus == "mixed_flow":
        creditor, debtor, saver = participants[0], participants[1], participants[2]
        debt, rest = _debt_pair(amount, rng)
        part = _partial(debt, rng)
        prepay = Decimal(_one_decimal(amount))
        refund = Decimal(_one_decimal(max(Decimal("0.1"), prepay / 2)))
        steps = [
            f"1. create_expense: amount {total} CNY, split_method manual, {creditor} pays {total}, "
            f"splits {{ {debtor}: {_one_decimal(debt)}, {creditor}: {_one_decimal(rest)} }}.",
            f"2. targeted_repayment: {debtor} repays {creditor} {_one_decimal(part)} CNY against "
            f"expense_1, strictly partial.",
            f"3. create_prepayment: owner {saver} pays {prepay} CNY to custodian {creditor}.",
            f"4. linked_refund of expense_1: amount -{_one_decimal(refund)} CNY, received by "
            f"{saver} and benefiting {debtor}; its payments and manual splits are negative and "
            f"each sum to exactly -{_one_decimal(refund)}.",
        ]
        return steps, [total, _one_decimal(debt), _one_decimal(rest), _one_decimal(part),
                       prepay, _one_decimal(refund)]

    if focus == "multi_currency":
        creditor, debtor = participants[0], participants[1]
        total_fx = Decimal(rng.choice(("12.34", "48.75", "7.20", "99.99", "3.05", "25.60")))
        total = _fmt(total_fx, 2)
        debt_fx, rest_fx = _partition(total_fx, 2, rng, scale=2)
        repay_fx = _partial(debt_fx, rng, scale=2)
        other = participants[2:]
        steps = [
            f"1. create_expense: amount {total} EUR — a FOREIGN currency; the activity base "
            f"currency stays CNY and the server resolves the FX snapshot, so the stored base "
            f"amount will differ from {total}. split_method manual, {creditor} pays {total} EUR, "
            f"splits {{ {debtor}: {_fmt(debt_fx, 2)}, {creditor}: {_fmt(rest_fx, 2)} }}"
            + (f", with {', '.join(other)} bearing nothing" if other else "")
            + f". {debtor} therefore owes {creditor} {_fmt(debt_fx, 2)} EUR.",
            f"2. fifo_repayment: {debtor} repays {creditor} {_fmt(repay_fx, 2)} EUR against that "
            f"foreign-currency debt, leaving part of it outstanding.",
        ]
        return steps, [total, _fmt(debt_fx, 2), _fmt(rest_fx, 2), _fmt(repay_fx, 2)]

    if focus == "final_settlement":
        payer, debtor_b, debtor_c = participants[0], participants[1], participants[2]
        # The third expense's payer must differ from the participant who bears it.
        payer_d = participants[3] if len(participants) > 3 else participants[2]
        first, second, third = _partition(amount, 3, rng)
        first, second, third = (_one_decimal(first), _one_decimal(second), _one_decimal(third))
        external = _one_decimal(_partial(Decimal(second), rng))
        steps = [
            f"1. create_expense: amount {first} CNY, split_method manual, {payer} pays {first}, "
            f"splits {{ {debtor_b}: {first} }} so {debtor_b} owes {payer} {first}.",
            f"2. create_expense: amount {second} CNY, split_method manual, {payer} pays {second}, "
            f"splits {{ {debtor_c}: {second} }} so {debtor_c} owes {payer} {second}.",
            f"3. create_expense: amount {third} CNY, split_method manual, {payer_d} pays {third}, "
            f"splits {{ {payer}: {third} }} so {payer} owes {payer_d} {third}.",
            "4. preview_final_settlement: mode base_unified. Record the plan the server offers "
            "right now — no accounts are written by a preview.",
            f"5. fifo_repayment: {debtor_c} repays {payer} {external} CNY outside the plan. This is "
            f"strictly less than the {second} CNY that {debtor_c} owes {payer}, so it is accepted, "
            f"and it makes the plan recorded in step 4 stale.",
            "6. preview_final_settlement: mode base_unified. The plan recorded here must differ "
            "from step 4 because of the external payment.",
            "7. final_settlement: mode base_unified. Execute the FIRST item of the CURRENT plan "
            "exactly as offered; do not choose an amount.",
        ]
        return steps, [first, second, third, external]

    if focus == "large_activity":
        payer, debtor = participants[0], participants[1]
        third = participants[2] if len(participants) > 2 else participants[1]
        one, two = _partition(amount, 2, rng)
        one, two = _one_decimal(one), _one_decimal(two)
        prepay = _one_decimal(amount)
        steps = [
            '1. create_sub_activity: name "Trip".',
            '2. create_sub_activity: name "Hotel".',
            f"3. create_expense inside the first sub-activity: use ledger_unit_ref sub_1, amount "
            f"{one} CNY, split_method manual, {payer} pays {one}, splits {{ {debtor}: {one} }} so "
            f"{debtor} owes {payer} {one}.",
            f"4. create_expense inside the second sub-activity: use ledger_unit_ref sub_2, amount "
            f"{two} CNY, split_method manual, {third} pays {two}, splits {{ {debtor}: {two} }} so "
            f"{debtor} owes {third} {two}.",
            f"5. create_prepayment at the ACTIVITY level (not inside a sub-activity): owner "
            f"{debtor} pays {prepay} CNY to custodian {payer}.",
        ]
        return steps, [one, two, prepay]

    if focus == "refund_boundary":
        payer, bearer = participants[0], participants[1]
        total = _one_decimal(amount)
        cap_exact = "refund_cap_boundary" in edge_tags and "cumulative_refund" in edge_tags
        first = _one_decimal(Decimal(total) / 2)
        second = _one_decimal(Decimal(total) - Decimal(first)) if cap_exact else _one_decimal(
            (Decimal(total) - Decimal(first)) * Decimal("0.8")
        )
        settled_first = "partial_repayment" in edge_tags
        steps = []
        index = 1
        steps.append(
            f"{index}. create_expense: amount {total} CNY, split_method manual, {payer} pays "
            f"{total}, splits {{ {bearer}: {total} }} so {bearer} owes {payer} {total}."
        )
        index += 1
        if settled_first:
            steps.append(
                f"{index}. fifo_repayment: {bearer} repays {payer} the whole {total} CNY, so the "
                f"original debt is already settled before any refund happens."
            )
            index += 1
        steps.append(
            f"{index}. linked_refund of expense_1: amount -{first} CNY, received by {payer} and "
            f"benefiting {bearer}; payments and manual splits are negative and each sum to "
            f"exactly -{first}."
        )
        index += 1
        steps.append(
            f"{index}. linked_refund of expense_1: amount -{second} CNY, again received by {payer} "
            f"and benefiting {bearer}. Together the two refunds come to "
            f"{_one_decimal(Decimal(first) + Decimal(second))} CNY against the {total} CNY source, "
            f"so they stay within the cumulative cap."
        )
        return steps, [total, first, second]

    if focus == "completion_archive":
        payer, bearer = participants[0], participants[1]
        total = _one_decimal(amount)
        cancelled = "cancel_archive" in edge_tags
        steps = [
            f"1. create_expense: amount {total} CNY, split_method manual, {payer} pays {total}, "
            f"splits {{ {bearer}: {total} }} so {bearer} owes {payer} {total}."
        ]
        if cancelled:
            steps.append(
                "2. archive_activity: archive even though the debt is still outstanding; the "
                "activity is read-only afterwards."
            )
            steps.append(
                "3. unarchive_activity: cancel the archive so the activity is writable again."
            )
        else:
            steps.append(
                f"2. fifo_repayment: {bearer} repays {payer} the whole {total} CNY, so no debt "
                f"remains and the activity can complete."
            )
            steps.append(
                "3. archive_activity: archive the fully settled activity. It must be the last "
                "operation."
            )
        return steps, [total]

    raise FocusDefinitionError(f"no plan skeleton for focus {focus}")


def render_plan(plan: ScenarioPlan) -> str:
    """Render the plan as the shape brief shared by the raw-case and Compiler stages."""
    spec = focus_spec(plan.focus)
    tags = ", ".join(plan.edge_tags) if plan.edge_tags else "none"
    return (
        f"FOCUS: {plan.focus} — {spec.title}\n"
        f"AIM: {spec.goal}\n"
        f"Use exactly these participants, in this order: {', '.join(plan.participants)}.\n"
        f"Amounts below are in {plan.currency}. Activity: type {spec.activity_types[0]}, "
        f"base_currency {spec.base_currency}, multi_currency_enabled "
        f"{'true' if spec.multi_currency else 'false'}.\n"
        f"Amount pattern: {plan.amount_pattern}. Edge tags to realise: {tags}.\n"
        f"Required operation shape (follow the order and the exact amounts):\n"
        + "\n".join(f"  {step}" for step in plan.steps)
        + f"\nEvery amount above is a decimal string with at most {spec.plan_amount_scale} "
        "fractional digit(s). Payments must sum exactly to their expense amount; manual splits "
        "must also sum exactly."
    )


def plan_from_dict(value: dict[str, object]) -> ScenarioPlan:
    """Rebuild a plan from its serialised form (run artifacts, tests)."""
    return ScenarioPlan(
        seed=int(value["seed"]),  # type: ignore[arg-type]
        focus=str(value["focus"]),
        participant_count=int(value["participant_count"]),  # type: ignore[arg-type]
        payer_count=int(value["payer_count"]),  # type: ignore[arg-type]
        amount_pattern=str(value["amount_pattern"]),
        operation_count=int(value["operation_count"]),  # type: ignore[arg-type]
        edge_tags=tuple(value["edge_tags"]),  # type: ignore[arg-type]
        currency=str(value["currency"]),
        participants=tuple(value["participants"]),  # type: ignore[arg-type]
        amounts=tuple(value["amounts"]),  # type: ignore[arg-type]
        steps=tuple(value["steps"]),  # type: ignore[arg-type]
    )


__all__ = [
    "AMOUNT_PATTERNS",
    "EDGE_TAGS",
    "ScenarioPlan",
    "plan_for",
    "plan_from_dict",
    "render_plan",
]
