"""AA allocation in both amount columns, exactly as the backend computes them.

These are **two different columns with two different quanta**, not a choice
between them:

* ``splits.amount`` -- original currency, quantum ``0.0001``
  (``p_original_amount * 10000`` units), from the AA branch of
  ``private.replace_expense_children``: ``trunc(total/n)`` per participant and
  the first ``|remainder|`` participants in ``participant_order, id`` move by
  one unit.
* ``splits.base_amount`` -- activity base currency, quantum ``0.1``
  (``base_amount * 10`` units), from
  ``private.redistribute_aa_split_base_amounts``: ``trunc(total/n)`` and the
  first ``|remainder|`` participants move by one unit.

The base rule is the one that ends up persisted.  ``replace_expense_children``
initially writes the base tail to the *last* participant, but every create,
update, delete, restore and repair path then calls
``redistribute_aa_split_base_amounts``, which overwrites the row set with the
first-N distribution.  Training data must therefore show the first-N result,
not the creation-time intermediate.

Amounts are positive in this dataset; the sign handling is reproduced anyway so
a reviewer can see the rule is the backend's and not a simplification.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

ORIGINAL_QUANTUM = Decimal("0.0001")
BASE_QUANTUM = Decimal("0.1")
ORIGINAL_DECIMALS = 4
BASE_DECIMALS = 1

_AMOUNT = re.compile(r"^-?[0-9]+(?:\.[0-9]{1,4})?$")


class AllocationError(ValueError):
    pass


def _units(amount: Decimal, quantum: Decimal) -> int:
    scaled = amount / quantum
    if scaled != scaled.to_integral_value():
        raise AllocationError(f"{amount} is not a whole number of {quantum} units")
    return int(scaled)


def _split_units(total_units: int, count: int) -> list[int]:
    """Backend integer division: truncate toward zero, remainder keeps its sign."""
    if count < 1:
        raise AllocationError("an allocation needs at least one participant")
    quotient = int(total_units / count)          # Python int() truncates toward zero
    remainder = total_units - quotient * count
    step = 1 if remainder > 0 else (-1 if remainder < 0 else 0)
    return [quotient + (step if index < abs(remainder) else 0) for index in range(count)]


def original_allocations(original_amount: str, count: int) -> list[Decimal]:
    """``splits.amount``: the backend's 0.0001 original-currency AA rule."""
    if not _AMOUNT.match(original_amount):
        raise AllocationError(f"malformed original amount: {original_amount}")
    units = _units(Decimal(original_amount), ORIGINAL_QUANTUM)
    return [(Decimal(unit) * ORIGINAL_QUANTUM).quantize(Decimal("0.0001"))
            for unit in _split_units(units, count)]


def expense_base_total(original_amount: str, fx_rate: Decimal) -> Decimal:
    """``expenses.base_amount``: each row's base is rounded to 0.1 independently."""
    return (Decimal(original_amount) * fx_rate).quantize(BASE_QUANTUM, rounding=ROUND_HALF_UP)


def base_allocations(base_total: Decimal, count: int) -> list[Decimal]:
    """``splits.base_amount``: the backend's 0.1 base-currency AA rule."""
    units = _units(base_total, BASE_QUANTUM)
    return [(Decimal(unit) * BASE_QUANTUM).quantize(Decimal("0.1"))
            for unit in _split_units(units, count)]


def last_person_allocations(base_total: Decimal, count: int) -> list[Decimal]:
    """The superseded creation-time shape: whole delta on the last participant."""
    units = _units(base_total, BASE_QUANTUM)
    quotient = int(units / count)
    shares = [quotient] * count
    shares[-1] += units - quotient * count
    return [(Decimal(unit) * BASE_QUANTUM).quantize(Decimal("0.1")) for unit in shares]


def is_last_person_fallback(allocations: Iterable[Decimal], base_total: Decimal) -> bool:
    """True when a row set is exactly the superseded creation-time shape.

    Comparing against the rule is the only safe test: for some remainders the
    first-N and last-person shapes both split the participants into two values,
    so a shape heuristic cannot tell them apart.  With no remainder the two
    shapes coincide and the answer is ``False`` (nothing was superseded).
    """
    values = [Decimal(value) for value in allocations]
    if len(values) < 2:
        return False
    if _units(base_total, BASE_QUANTUM) % len(values) == 0:
        return False
    return values == last_person_allocations(base_total, len(values))


def verify_column(amounts: Iterable[str | Decimal], total: Decimal, *, quantum: Decimal,
                  decimals: int) -> Decimal:
    """Sum a column and require exact conservation at its own quantum."""
    values = [Decimal(str(value)) for value in amounts]
    for value in values:
        if (value / quantum) != (value / quantum).to_integral_value():
            raise AllocationError(f"{value} is not on the {quantum} grid")
    summed = sum(values, Decimal(0))
    if summed.quantize(quantum) != total.quantize(quantum):
        raise AllocationError(f"column sums to {summed}, expected {total}")
    return summed.quantize(Decimal(1).scaleb(-decimals))
