"""Offline checks for the reproducible ScenarioPlan generator."""

from __future__ import annotations

import unittest
from decimal import Decimal

from shared_ledger_verifier.focus_contract import ALL_FOCUSES, focus_spec
from shared_ledger_verifier.scenario_plan import (
    ScenarioPlan,
    check_plan,
    plan_for,
    plan_from_dict,
    render_plan,
)

_SEEDS = range(0, 40)


class ScenarioPlanTests(unittest.TestCase):
    def test_plans_are_reproducible_for_a_seed(self):
        for focus in ALL_FOCUSES:
            for seed in (0, 1, 7, 23):
                self.assertEqual(plan_for(focus, seed), plan_for(focus, seed), f"{focus}/{seed}")
                self.assertEqual(
                    plan_for(focus, seed).fingerprint(),
                    plan_for(focus, seed).fingerprint(),
                )

    def test_different_seeds_change_the_business_data(self):
        for focus in ALL_FOCUSES:
            fingerprints = {plan_for(focus, seed).fingerprint() for seed in _SEEDS}
            # Every focus must move: a batch that cannot vary is not coverage.
            self.assertGreater(len(fingerprints), 1, focus)
            self.assertGreaterEqual(
                len(fingerprints), 5,
                f"{focus} produced only {len(fingerprints)} distinct plans over {len(_SEEDS)} seeds",
            )

    def test_every_plan_satisfies_its_own_focus_spec(self):
        for focus in ALL_FOCUSES:
            spec = focus_spec(focus)
            for seed in _SEEDS:
                plan = plan_for(focus, seed)
                with self.subTest(focus=focus, seed=seed):
                    self.assertIsNone(check_plan(plan))
                    self.assertLessEqual(spec.participants[0], plan.participant_count)
                    self.assertLessEqual(plan.participant_count, spec.participants[1])
                    self.assertIn(plan.payer_count, spec.payers)
                    self.assertIn(plan.amount_pattern, spec.amount_patterns)
                    self.assertIn(plan.operation_count, spec.operation_counts)
                    self.assertLessEqual(set(plan.edge_tags), set(spec.edge_tags))

    def test_every_plan_leaves_a_pure_debtor(self):
        for focus in ALL_FOCUSES:
            for seed in _SEEDS:
                plan = plan_for(focus, seed)
                with self.subTest(focus=focus, seed=seed):
                    self.assertLess(plan.payer_count, plan.participant_count)

    def test_aa_rounding_plans_always_leave_a_remainder(self):
        for seed in _SEEDS:
            plan = plan_for("aa_rounding", seed)
            amount = Decimal(plan.amounts[0])
            scaled = int((amount * Decimal(10_000)).to_integral_value())
            self.assertNotEqual(scaled % plan.participant_count, 0, f"seed {seed} amount {amount}")

    def test_amounts_stay_inside_the_base_currency_scale(self):
        for focus in ALL_FOCUSES:
            for seed in _SEEDS:
                for amount in plan_for(focus, seed).amounts:
                    value = Decimal(amount)
                    self.assertLessEqual(max(0, -value.as_tuple().exponent), 1, f"{focus}/{seed}")

    def test_participant_rosters_are_loader_safe_refs(self):
        for focus in ALL_FOCUSES:
            plan = plan_for(focus, 3)
            self.assertEqual(len(set(plan.participants)), len(plan.participants))
            for name in plan.participants:
                self.assertRegex(name, r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

    def test_coverage_focuses_change_participant_counts(self):
        observed = {
            focus: {plan_for(focus, seed).participant_count for seed in range(0, 40)}
            for focus in ("single_payer_aa", "multi_payer_aa", "manual_split", "fifo_repayment")
        }
        for focus, counts in observed.items():
            self.assertGreater(len(counts), 1, f"{focus} never varied its participant count: {counts}")

    def test_rendered_plan_states_participants_and_amounts(self):
        plan = plan_for("multi_payer_aa", 3)
        rendered = render_plan(plan)
        self.assertIn(plan.focus, rendered)
        for name in plan.participants:
            self.assertIn(name, rendered)
        for amount in plan.amounts:
            self.assertIn(amount, rendered)

    def test_plan_round_trips_through_its_serialised_form(self):
        for focus in ALL_FOCUSES:
            plan = plan_for(focus, 5)
            self.assertEqual(plan_from_dict(plan.as_dict()), plan)
            self.assertEqual(plan_from_dict(plan.as_dict()).fingerprint(), plan.fingerprint())

    def test_check_plan_reports_dimension_drift(self):
        plan = plan_for("multi_payer_aa", 1)
        broken = ScenarioPlan(**{**plan.as_dict(), "participant_count": 99})
        self.assertIn("participants", check_plan(broken) or "")
        broken_amount = ScenarioPlan(**{**plan.as_dict(), "amounts": ("1.23",)})
        self.assertIn("fractional", check_plan(broken_amount) or "")


if __name__ == "__main__":
    unittest.main()
