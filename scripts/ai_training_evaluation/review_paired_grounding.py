#!/usr/bin/env python3
"""Build the fixed post-inference fact review from the paired diagnostic run."""
from __future__ import annotations
import hashlib, json, re, difflib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/paired_grounding_diagnostic"
V01 = ROOT / "docs/ai/dataset/canonical_training/v0.1"
SAMPLE_FACT_ASSESSMENT = {
    "scenario_gs_p0b_009": {
        "a": "mixed_or_unsupported_currency/order_claims", "b": "correct_partial_direct_rule_use",
        "improve": 5, "regress": 0, "neutral": 1,
        "note": "B correctly states same-currency repayment and owner/creditor order, but often omits a direct USD-versus-JPY sentence. It copies exact policy sentences in all six rows. A includes unsupported cross-currency/oldest-debt claims in several rows.",
    },
    "scenario_gs_p0b_033": {
        "a": "partial_or_wrong_rounding_mechanism", "b": "correct_and_receipt_supported",
        "improve": 4, "regress": 0, "neutral": 0,
        "note": "B explains stable participant ordering and smallest-unit allocation. It reproduces a long exact receipt sentence in three rows. A attributes the distribution to ordinary rounding and does not state the frozen deterministic rule.",
    },
    "scenario_gs_p0b_034": {
        "a": "generic_or_wrong_debt_order", "b": "correct_partial_receipt_supported",
        "improve": 6, "regress": 0, "neutral": 0,
        "note": "B states that prepayment first clears the qualifying Owner-to-Custodian debt and remaining value enters the account; longer answers copy receipt text. A invents generic activity-debt/personal-debt or principal/interest ordering.",
    },
    "scenario_gs_p0b_035": {
        "a": "mixed_lock_explanation", "b": "correct_for_five_nonclarification_rows",
        "improve": 5, "regress": 0, "neutral": 1,
        "note": "B accurately says deleting refunds does not release the original Expense financial lock and only frees refund capacity. One row remains an unnecessary clarification asking for original_expense_id and posits other linked refunds; both arms fail to answer that row's general rule question.",
    },
    "scenario_gs_p0b_036": {
        "a": "already_generally_correct", "b": "correct_more_explicit_confirmation_gate",
        "improve": 0, "regress": 0, "neutral": 5,
        "note": "Both arms generally preserve the pending-confirmation state. B adds trusted UI/Gateway details from the receipt in some rows; this did not materially change correctness.",
    },
    "scenario_gs_p0b_038": {
        "a": "generic_but_directionally_correct_refresh_and_reread", "b": "mixed_with_new_unsupported_version_cause",
        "improve": 1, "regress": 4, "neutral": 1,
        "note": "Four B rows assert the proposal baseline_commit mismatches latest server state, but the receipt only says page/entity/server state or financial_version changes invalidate a proposal; it does not report a proposal baseline_commit comparison. One B row says reload an existing proposal where the receipt requires invalidation and regeneration. One B row gives the correct regenerate/reconfirm action without the unsupported commit claim; another mixes the correct action with the unsupported cause. This is the main new unsupported fact pattern.",
    },
    "scenario_gs_p0b_039": {
        "a": "mixed_including_wrong_or_nonresponsive_archive_guidance", "b": "correct_for_five_rows_one_unsupported_activity_claim",
        "improve": 5, "regress": 1, "neutral": 0,
        "note": "B correctly states archived financial writes are read-only and recommends unarchive before recording. One B row claims the new transaction would be handled as an independent activity; neither receipt nor frozen context supports that. Most B answers are paraphrases rather than exact receipt copies.",
    },
}
BACKEND_NOTE = "No grounded-correctness credit is assigned. The visible frozen entity/result aliases do not equal the actual receipt UUID, no alias map is given to the model, and receipt observed_at postdates the frozen context. Raw original evaluator metrics are retained; UUID equivalence remains an external-only diagnostic."
LONG_COPY_RE = re.compile(r"[。；]")
ROW_DISPOSITION = {
    "sample_gs_p0_034":"improve", "sample_gs_p0_035":"neutral",
    "sample_teacher_e24b1a12d1e4":"improve", "sample_teacher_ae1660aab544":"improve",
    "sample_teacher_2b0ab71ccf9c":"improve", "sample_teacher_7e6dab2d3489":"improve",
    "sample_gs_p0_080":"improve", "sample_gs_p0_081":"improve",
    "sample_teacher_b6a3bfa9da68":"improve", "sample_teacher_d128b17c1db8":"improve",
    "sample_gs_p0_082":"improve", "sample_gs_p0_083":"improve",
    "sample_teacher_401a2f5ad127":"improve", "sample_teacher_f3941370d729":"improve",
    "sample_teacher_191d11c1745f":"improve", "sample_teacher_6c16bbf26c83":"improve",
    "sample_gs_p0_084":"improve", "sample_gs_p0_085":"improve",
    "sample_teacher_495133fe795c":"improve", "sample_teacher_af85b5a16d3b":"neutral",
    "sample_teacher_2a2434a010ba":"improve", "sample_teacher_8e1096f2010d":"improve",
    "sample_gs_p0_086":"neutral", "sample_gs_p0_087":"neutral",
    "sample_teacher_0847b1b27f7f":"neutral", "sample_teacher_538a5e7bdb1e":"neutral",
    "sample_teacher_720594c4fe1e":"neutral",
    "sample_gs_p0_090":"regress", "sample_gs_p0_091":"neutral",
    "sample_teacher_c2e46813f818":"regress", "sample_teacher_0c10938359b3":"regress",
    "sample_teacher_95b271a2d3c6":"improve", "sample_teacher_a75531445264":"regress",
    "sample_gs_p0_092":"improve", "sample_gs_p0_093":"improve",
    "sample_teacher_5d586b9bd796":"improve", "sample_teacher_ba1b62eae9d7":"improve",
    "sample_teacher_f0b77cc4c158":"regress", "sample_teacher_fa5cc2f3d068":"improve",
}
A_FULL_PASS = {
    "sample_gs_p0_035", "sample_teacher_2b0ab71ccf9c",
    "sample_gs_p0_086", "sample_gs_p0_087", "sample_teacher_0847b1b27f7f",
    "sample_teacher_538a5e7bdb1e", "sample_teacher_720594c4fe1e",
    "sample_gs_p0_091", "sample_teacher_c2e46813f818", "sample_teacher_0c10938359b3",
    "sample_teacher_a75531445264",
}
B_FULL_PASS = {
    "sample_gs_p0_034", "sample_gs_p0_035", "sample_teacher_e24b1a12d1e4",
    "sample_teacher_ae1660aab544", "sample_teacher_2b0ab71ccf9c", "sample_teacher_7e6dab2d3489",
    "sample_gs_p0_080", "sample_gs_p0_081", "sample_teacher_b6a3bfa9da68", "sample_teacher_d128b17c1db8",
    "sample_gs_p0_082", "sample_gs_p0_083", "sample_teacher_401a2f5ad127", "sample_teacher_f3941370d729",
    "sample_teacher_191d11c1745f", "sample_teacher_6c16bbf26c83",
    "sample_gs_p0_084", "sample_gs_p0_085", "sample_teacher_495133fe795c",
    "sample_teacher_2a2434a010ba", "sample_teacher_8e1096f2010d",
    "sample_gs_p0_086", "sample_gs_p0_087", "sample_teacher_0847b1b27f7f",
    "sample_teacher_538a5e7bdb1e", "sample_teacher_720594c4fe1e",
    "sample_teacher_95b271a2d3c6",
    "sample_gs_p0_092", "sample_gs_p0_093", "sample_teacher_5d586b9bd796",
    "sample_teacher_ba1b62eae9d7", "sample_teacher_fa5cc2f3d068",
}

def load(p: Path): return json.loads(p.read_text(encoding="utf-8"))
def sha(p: Path): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    records = [json.loads(x) for x in (OUT / "generation_records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    by = defaultdict(dict)
    for row in records: by[row["sample_id"]][row["arm"]] = row
    samples = {x["sample_id"]: x for x in load(V01 / "samples.json")}
    if len(by) != 48 or any(set(x) != {"A", "B"} for x in by.values()): raise ValueError("expected 48 complete A/B pairs")
    rows=[]; counts=Counter(); state_counts={}
    for sid, arms in by.items():
        a,b=arms["A"],arms["B"]
        fixture_kind=b["fixture_kind"]
        backend=fixture_kind != "new_frozen_document_read_fixture"
        if backend:
            rating={"A_fact_status":"not_receipt_grounded_no_body", "B_fact_status":"id_and_time_confounded", "human_change":"not_counted",
                    "A_full_fact_pass":None,"B_full_fact_pass":None,
                    "unsupported_or_hallucinated_fact":"cannot assign to authoritative result because actual UUID binding is not visible; keep raw response for review",
                    "receipt_citation":"B cites frozen legacy ID when present, never actual UUID; this is not an actual receipt citation",
                    "copying":"not scored"}
        else:
            s=SAMPLE_FACT_ASSESSMENT[b["scenario_id"]]
            bid=b.get("parsed_output") or {}
            aid=a.get("parsed_output") or {}
            bcontent=bid.get("content","") if isinstance(bid,dict) else ""
            acontent=aid.get("content","") if isinstance(aid,dict) else ""
            receipt=b.get("authoritative_receipt",{}).get("data",{})
            source="".join(x.get("text","") for x in receipt.get("passages",[]) if isinstance(x,dict)) if isinstance(receipt,dict) else ""
            exact_long=any(len(sentence.strip()) >= 20 and sentence.strip() in bcontent for sentence in LONG_COPY_RE.split(source) if sentence.strip())
            sim=difflib.SequenceMatcher(None,bcontent,source).ratio() if bcontent and source else None
            base={"A_fact_status":s["a"],"B_fact_status":s["b"],
                  "A_full_fact_pass":sid in A_FULL_PASS,"B_full_fact_pass":sid in B_FULL_PASS,
                  "A_receipt_body_available":False,"B_receipt_body_available":True,
                  "human_change":"improved" if sid in set() else "scenario_review", # replaced below with preregistered row disposition
                  "unsupported_or_hallucinated_fact":None,
                  "receipt_citation":"correct frozen result ID cited" if b.get("receipt_result_id") in bid.get("evidence_result_ids",[]) else "no exact receipt citation",
                  "copying":"long exact receipt sentence copied" if exact_long else ("near-verbatim/partial phrase overlap" if sim is not None and sim >= 0.30 else "paraphrase or synthesis"),
                  "receipt_text_similarity_sequence_ratio":round(sim,3) if sim is not None else None}
            # Fixed row disposition from the pre-declared scenario review rubric.
            row_change=ROW_DISPOSITION[sid]
            base["human_change"]=row_change
            if b["scenario_id"]=="scenario_gs_p0b_038" and "baseline_commit" in bcontent:
                base["unsupported_or_hallucinated_fact"]="claims proposal baseline_commit mismatch/latest-state comparison absent from authoritative receipt"
            if sid=="sample_teacher_f0b77cc4c158":
                base["unsupported_or_hallucinated_fact"]="claims the new transaction would be an independent activity; source only permits unarchive then live projection"
            rating=base
            state_counts.setdefault(b["scenario_id"],{"rows":0,"improve":0,"regress":0,"neutral":0})
            state_counts[b["scenario_id"]]["rows"]+=1
            state_counts[b["scenario_id"]][row_change]+=1
        counts["backend_rows" if backend else "static_rows"]+=1
        counts["backend_uuid_mismatches" if backend and b["backend_id_mismatch"] else "static_row" if not backend else "backend_uuid_match"]+=1
        if not backend:
            counts["static_exact_receipt_citations"] += rating["receipt_citation"]=="correct frozen result ID cited"
            counts["static_long_exact_copy_rows"] += rating["copying"]=="long exact receipt sentence copied"
            counts["static_unsupported_rows"] += rating["unsupported_or_hallucinated_fact"] is not None
        rows.append({"sample_id":sid,"scenario_id":b["scenario_id"],"split":b["split"],"fixture_kind":fixture_kind,
                     "tool":b["tool"],"legacy_result_id":b["legacy_result_id"],"receipt_result_id":b["receipt_result_id"],
                     "expected_verified_result_ids":b["expected_verified_result_ids"],
                     "B_cites_actual_receipt_id":b["receipt_result_id"] in (b.get("parsed_output") or {}).get("evidence_result_ids",[]) if isinstance(b.get("parsed_output"),dict) else False,
                     "frozen_context_generated_at":b["frozen_context_generated_at"],
                     "receipt_observed_at_later_than_frozen_context":b["receipt_observed_at_later_than_frozen_context"],
                     "A_output":a["parsed_output"],"B_output":b["parsed_output"],
                     "expected_output":samples[sid]["expected"]["model_output"],**rating,
                     "backend_grounding_limitation":BACKEND_NOTE if backend else None})
    static_delta=sum(v["improve"]-v["regress"] for v in state_counts.values())
    full_pass_by_state={}
    for scenario in sorted(state_counts):
        ids=[sid for sid,x in by.items() if x["A"]["scenario_id"]==scenario]
        ap=sum(sid in A_FULL_PASS for sid in ids); bp=sum(sid in B_FULL_PASS for sid in ids); n=len(ids)
        full_pass_by_state[scenario]={"rows":n,"A_correct_pass":ap,"A_rate":ap/n if n else None,
            "B_correct_pass":bp,"B_rate":bp/n if n else None,
            "delta_percentage_points":((bp-ap)/n*100) if n else None,
            "A_receipt_body_available":False,
            "B_receipt_source_citation_count":sum(isinstance(by[sid]["B"].get("parsed_output"),dict)
                and by[sid]["B"]["receipt_result_id"] in by[sid]["B"]["parsed_output"].get("evidence_result_ids",[]) for sid in ids)}
    improving_states=[s for s,v in full_pass_by_state.items() if v["delta_percentage_points"]>=50]
    regressing_states=[s for s,v in full_pass_by_state.items() if v["delta_percentage_points"]<=-50]
    report={"review_method":"Manual pairwise review of each user request, Expected GT, complete authoritative receipt text and A/B answer; response facts are rated supported/correct, partial, wrong/nonresponsive, or blocked by receipt ID scope. Exact substring and sequence similarity support the separate copying check.",
            "rows":rows,"static_state_summary":state_counts,"summary":{"static_rows":39,"backend_rows":9,"static_exact_receipt_citations":counts["static_exact_receipt_citations"],
            "static_long_exact_copy_rows":counts["static_long_exact_copy_rows"],"static_rows_with_new_unsupported_claim":counts["static_unsupported_rows"],
            "directional_change_counts_not_full_pass_counts":state_counts,
            "A_B_full_fact_pass_by_state":full_pass_by_state,
            "manual_directional_net_row_change_not_exact_pass_count":static_delta,
            "static_states_with_at_least_50pp_improvement_in_full_fact_pass_rate":improving_states,
            "static_states_with_at_least_50pp_regression":regressing_states,
            "backend_uuid_mismatches":counts["backend_uuid_mismatches"],"backend_grounding_credit":0,
            "state_verdict":"mixed: gains in policy explanation states; one state has repeated unsupported baseline_commit claims; archive answers improve with one unsupported transaction-path claim"},
            "scenario_notes":SAMPLE_FACT_ASSESSMENT,
            "decision_against_preregistered_threshold":"EXPERIMENT_B_GROUNDING_SIGNAL_WEAK",
            "decision_reason":"Although the fixed receipt body improves grounded explanations across multiple policy states and the original evaluator shows structural gains, the manual static full-pass comparison identifies a >=50 percentage-point regression state from repeated unsupported baseline_commit explanations. The positive gate also requires no such state regression. Backend rows receive no correctness credit because receipt UUIDs are not model-visible verified IDs. No new dangerous write/bypass appeared.",
            "reviewed_at":datetime.now(timezone.utc).isoformat()}
    (OUT/"manual_fact_review.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    pair_reviews=load(OUT/"pair_reviews.json")
    manual_by={x["sample_id"]:x for x in rows}
    for pair in pair_reviews:
        m=manual_by[pair["sample_id"]]
        pair["human_fact_grounding_review"]={"A_fact_status":m["A_fact_status"],"B_fact_status":m["B_fact_status"],
            "human_change":m["human_change"],"unsupported_or_hallucinated_fact":m["unsupported_or_hallucinated_fact"],
            "receipt_citation":m["receipt_citation"],"copying":m["copying"],
            "backend_grounding_limitation":m["backend_grounding_limitation"]}
    (OUT/"pair_reviews.json").write_text(json.dumps(pair_reviews,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    automated=load(OUT/"automated_summary.json")
    automated["decision"]="EXPERIMENT_B_GROUNDING_SIGNAL_WEAK"
    automated["human_review_summary"]=report["summary"]
    (OUT/"automated_summary.json").write_text(json.dumps(automated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False))

if __name__=="__main__": main()
