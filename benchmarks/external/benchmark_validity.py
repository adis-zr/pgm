"""Prospective output semantics for the second external performance round.

A comparator process killed by the resource supervisor has not returned an
accepted answer. Its partially written MAR file is retained as diagnostic bytes,
not parsed into an answer. Identity, receipt and cleanup checks remain mandatory.
The first round did not declare this rule and keeps its original strict verdict.
"""
from __future__ import annotations

RESOURCE_KILLS = frozenset(("TIMEOUT_KILL", "MEMORY_KILL"))


def censored_comparator(frozen, arm, receipt):
    rules = (frozen.get("protocol") or {}).get("output_validation") or {}
    return bool(rules.get("resource_killed_comparator") == "censored_nonanswer"
                and arm in ("LIBDAI_JT", "LIBDAI_BP")
                and receipt.get("outcome") in RESOURCE_KILLS)


def censored_fields(receipt):
    return dict(output_valid=False, contract_valid=True, all_queries_returned=False,
                output_validation="CENSORED_NONANSWER", censored_output=True,
                censored_reason=receipt["outcome"], solver_outcome=None,
                validation_faults=[], contract_faults=[])


def check_public_output(frozen, path, task, contract, receipt):
    """Retain the original validator, with one prospectively declared refusal rule.

    A missed inner publication deadline can validly suppress every answer and
    return a typed refusal before the outer supervisor deadline. This is never
    a successful inference or a finite latency denominator. No other original
    contract fault is removed, and earlier campaign freezes remain strict.
    """
    import json
    import math
    from pathlib import Path
    import run_suite as original

    checked = original.check_pgm(path, task, contract, frozen.get("budget_s", 20))
    rules = (frozen.get("protocol") or {}).get("output_validation") or {}
    raw = json.loads(Path(path).read_text())
    if rules.get("claimed_publication_timestamps") == "finite_within_cli_and_recorded_api_budgets":
        claimed = checked.get("published", 0) > 0 or raw.get("outcome") in ("COMPLETE", "EXACT")
        if claimed:
            def number(value):
                return type(value) in (int, float) and math.isfinite(value) and value >= 0
            faults = list(checked.get("contract_faults", []))
            cli_wall = raw.get("wall_s")
            cli_allowance = frozen.get("pgm_allowance_s", 19.5)
            if not number(cli_wall) or not number(cli_allowance) or cli_wall > cli_allowance:
                faults.append("published/completing result has invalid or late CLI wall")
            requested = raw.get("requested_budget_s")
            if "requested_budget_s" in raw and (not number(requested) or requested <= 0 or requested > cli_allowance):
                faults.append("published/completing result has invalid requested API budget")
            if "api_wall_s" in raw:
                api_wall = raw["api_wall_s"]
                if (not number(api_wall) or not number(requested) or requested <= 0
                        or api_wall > requested or not number(cli_wall) or api_wall > cli_wall):
                    faults.append("published/completing result has invalid or late API wall")
            if "api_hard_deadline_respected" in raw and raw["api_hard_deadline_respected"] is not True:
                faults.append("published/completing result has a refused API publication deadline")
            checked["contract_faults"] = sorted(set(faults))
            checked["contract_valid"] = not faults
    rule = rules.get("late_empty_deadline_refusal")
    if rule != "typed_nonanswer_with_clean_outer_completion":
        return checked
    answers = raw.get("answers")
    wall = raw.get("wall_s")
    outer_wall = receipt.get("wall_s")
    coherent = bool(
        checked.get("output_valid") is True
        and raw.get("outcome") == "DEADLINE" and raw.get("guarantee") == "NONE"
        and type(raw.get("published")) is int and raw["published"] == 0 and checked.get("published") == 0
        and raw.get("hard_deadline_respected") is False and raw.get("max_published_radius") is None
        and isinstance(answers, list) and all(
            row.get("guarantee") == "NOT_PUBLISHED" and all(row.get(field) is None for field in ("lo", "hi", "point"))
            for row in answers)
        and isinstance(wall, (int, float)) and not isinstance(wall, bool) and math.isfinite(wall) and wall >= 0
        and isinstance(outer_wall, (int, float)) and math.isfinite(outer_wall)
        and 0 <= wall <= outer_wall <= frozen.get("budget_s", 20)
        and receipt.get("outcome") == "COMPLETED" and receipt.get("returncode") == 0
        and receipt.get("cleanup_unresolved") is False and receipt.get("group_empty_at_receipt") is True
        and receipt.get("nested_groups_live_at_receipt") == 0
    )
    if coherent and "hard deadline not respected" in checked.get("contract_faults", []):
        checked["contract_faults"] = [fault for fault in checked["contract_faults"] if fault != "hard deadline not respected"]
        checked["contract_valid"] = not checked["contract_faults"]
        checked["all_queries_returned"] = False
        checked["late_empty_deadline_refusal"] = True
        checked["late_refusal_wall_s"] = wall
        checked["late_refusal_api_wall_s"] = raw.get("api_wall_s")
    return checked
