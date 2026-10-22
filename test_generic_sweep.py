"""
test_generic_sweep.py - routes-only before/after sweep for the generic-symptom
over-triage work described in docs/context-and-implimentation.md (Fixes 1-4).

Every case is graded WITHOUT calling the LLM, so a run takes seconds and is
deterministic. Per case we record and grade:

  * the detector route (keyword_detector.keywords.detect) and its severity hint
  * chat.py's separate substring router (detect_route) - both routers must
    AGREE, otherwise chat.py's _detector_top_row() silently falls back to its
    own word search and the two answers diverge
  * the top verified row the pipeline actually picks (condition / medicine)
  * whether the winning row (or the severity hint) is CRITICAL - that is the
    red "ACT NOW" banner case this work exists to stop

Two kinds of cases:
  * benign  - a plain question ("i have a headache") must NOT land on a
              CRITICAL row / CRITICAL hint. This is the bug being fixed.
  * control - a genuine emergency ("thunderclap headache") MUST stay CRITICAL.
              These are the regression guards: a fix that demotes everything
              has failed just as badly as the original bug.

Usage:
    python test_generic_sweep.py --out before     # -> test_results/generic_sweep_before.json
    python test_generic_sweep.py --out after      # -> test_results/generic_sweep_after.json
    python test_generic_sweep.py --report         # -> test_results/generic_sweep_report.txt
                                                  #    (before vs after, from the two JSONs)

--out is mandatory and an existing snapshot is never overwritten without
--force: the BEFORE baseline has to stay the measurement taken before the
fixes, so a later run can never silently replace it.
"""

import os
import sys
import json
import argparse
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from keyword_detector.keywords import detect, run as detect_and_query      # noqa: E402
import chat as chat_module                                                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS_DIR = os.path.join(BASE_DIR, "test_results")

# ---------------------------------------------------------------------------
# CASE TABLE
#
#   expect_route : route BOTH routers must choose
#   expect_top   : acceptable labels of the winning row, case-insensitive
#                  substring match (None = any row is acceptable)
#   benign       : the winning row / hint must NOT be CRITICAL
#   control      : the case MUST end up CRITICAL (override, hint or row)
# ---------------------------------------------------------------------------
CASES = [
    # --- the live-user bug, plus the benign generic-symptom family --------
    {"id": "med_for_headache", "benign": True,
     "text": "what med should i consume if i had headache",
     "expect_route": "medicines",
     "expect_top": ["paracetamol", "ibuprofen", "aspirin"]},
    {"id": "headache_plain", "benign": True,
     "text": "i have a headache",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "head_hurts", "benign": True,
     "text": "my head hurts",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "dizzy", "benign": True,
     "text": "i feel dizzy",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "fever", "benign": True,
     "text": "i have a fever",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "vomiting", "benign": True,
     "text": "i am vomiting",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "stomach_pain", "benign": True,
     "text": "my stomach hurts",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "weakness", "benign": True,
     "text": "i feel very weak",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "sore_throat", "benign": True,
     "text": "sore throat",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "rash", "benign": True,
     "text": "i have a rash",
     "expect_route": "body_symptoms", "expect_top": None},

    # --- red-flag controls: MUST stay CRITICAL ---------------------------
    {"id": "worst_headache", "control": True,
     "text": "worst headache of my life",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "headache_stiffneck_fever", "control": True,
     "text": "headache with stiff neck and fever",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "thunderclap", "control": True,
     "text": "thunderclap headache",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "chest_pain_breathless", "control": True,
     "text": "my chest hurts and i cant breathe",
     "expect_route": "body_symptoms", "expect_top": None},
    {"id": "named_drug_overdose", "control": True,
     "text": "i took too many paracetamol",
     "expect_route": "medicines", "expect_top": None},
]


def _top_label(route, rows):
    """Short label of the winning row, whatever route produced it."""
    if not rows:
        return "(no row)"
    row = rows[0]
    if route == "medicines":
        label = row.get("medicine_name") or row.get("name") or "(unnamed)"
    elif route == "emergency_numbers":
        label = row.get("country") or "(unknown)"
    else:
        label = row.get("condition") or "(unnamed)"
    sev = row.get("severity")
    return "%s (%s)" % (label, sev) if sev else str(label)


def _top_severity(route, rows):
    """CRITICAL only when the winning row (or, for medicine rows with no
    severity column, nothing) says so; the hint is graded separately."""
    if not rows:
        return None
    return rows[0].get("severity")


def evaluate_case(case):
    text = case["text"]
    det = detect(text)
    result = detect_and_query(text)
    rows = result.get("db_results") or []
    route = det.get("route")
    chat_route = chat_module.detect_route(text)
    hint = det.get("severity_hint")
    override = bool(det.get("critical_override"))
    top = _top_label(route, rows)
    top_sev = _top_severity(route, rows)

    # Both routers must agree - chat.py's detector fallback returns None on a
    # route mismatch and silently answers from its own word search instead.
    route_ok = (route == case["expect_route"] and chat_route == case["expect_route"])

    expect_top = case.get("expect_top")
    top_ok = (expect_top is None or not rows or any(
        s in top.lower() for s in expect_top))

    if case.get("control"):
        # A genuine emergency keeps the red path by ANY of: critical override,
        # CRITICAL severity hint, or a CRITICAL winning row.
        severity_ok = override or hint == "CRITICAL" or top_sev == "CRITICAL"
    else:
        # A benign question must not be dressed up as life-threatening.
        severity_ok = top_sev != "CRITICAL" and hint != "CRITICAL"

    return {
        "id": case["id"],
        "text": text,
        "expect_route": case["expect_route"],
        "expect_top": expect_top,
        "kind": "control" if case.get("control") else "benign",
        "detector_route": route,
        "chat_route": chat_route,
        "severity_hint": hint,
        "critical_override": override,
        "matched_keywords": det.get("matched_keywords", []),
        "top_row": top,
        "top_severity": top_sev,
        "route_ok": route_ok,
        "top_ok": top_ok,
        "severity_ok": severity_ok,
        "passed": route_ok and top_ok and severity_ok,
    }


def run_sweep(out_name):
    started = datetime.datetime.now().isoformat(timespec="seconds")
    cases = []
    for case in CASES:
        rec = evaluate_case(case)
        flag = "OK  " if rec["passed"] else "FAIL"
        print("[%s] %-26s %-16s -> %-16s top: %s"
              % (flag, rec["id"], rec["detector_route"], rec["chat_route"],
                 rec["top_row"]))
        if not rec["passed"]:
            reasons = []
            if not rec["route_ok"]:
                reasons.append("route(detector=%s, chat=%s, want=%s)"
                               % (rec["detector_route"], rec["chat_route"],
                                  rec["expect_route"]))
            if not rec["top_ok"]:
                reasons.append("top=%s want=%s" % (rec["top_row"], rec["expect_top"]))
            if not rec["severity_ok"]:
                reasons.append("severity(hint=%s, top=%s, override=%s)"
                               % (rec["severity_hint"], rec["top_severity"],
                                  rec["critical_override"]))
            print("       -> " + "; ".join(reasons))
        cases.append(rec)

    passed = sum(1 for c in cases if c["passed"])
    payload = {
        "generated": started,
        "out": out_name,
        "model_note": "routes only - no LLM calls, fully deterministic",
        "summary": {"total": len(cases), "passed": passed,
                    "failed": len(cases) - passed},
        "cases": cases,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, "generic_sweep_%s.json" % out_name)
    if os.path.exists(path) and not FORCE_OVERWRITE:
        print("refusing to overwrite existing %s (use --force to replace)" % path)
        return 2
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print("\n%d/%d cases passed -> %s" % (passed, len(cases), path))
    return 0 if passed == len(cases) else 1


def _load(name):
    path = os.path.join(RESULTS_DIR, "generic_sweep_%s.json" % name)
    if not os.path.exists(path):
        print("missing %s - run `python test_generic_sweep.py --out %s` first"
              % (path, name))
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def make_report():
    before = _load("before")
    after = _load("after")
    if not before or not after:
        return 1
    after_by_id = {c["id"]: c for c in after["cases"]}

    lines = []
    lines.append("GENERIC-SYMPTOM SWEEP - BEFORE vs AFTER (routes only, no LLM)")
    lines.append("before: %s   %d/%d passed"
                 % (before["generated"], before["summary"]["passed"],
                    before["summary"]["total"]))
    lines.append("after:  %s   %d/%d passed"
                 % (after["generated"], after["summary"]["passed"],
                    after["summary"]["total"]))
    lines.append("")
    lines.append("%-26s %-34s %-38s %s"
                 % ("CASE", "ROUTE before -> after", "TOP ROW before -> after",
                    "VERDICT"))
    lines.append("-" * 120)
    regressed = []
    for cb in before["cases"]:
        ca = after_by_id.get(cb["id"])
        if not ca:
            continue
        route_cell = "%s -> %s" % (cb["detector_route"], ca["detector_route"])
        top_cell = "%s -> %s" % (cb["top_row"][:17], ca["top_row"][:17])
        if cb["passed"] and not ca["passed"]:
            verdict = "REGRESSED"
            regressed.append(cb["id"])
        elif ca["passed"] and not cb["passed"]:
            verdict = "FIXED"
        elif ca["passed"]:
            verdict = "OK (unchanged)"
        else:
            verdict = "STILL FAILING"
        lines.append("%-26s %-34s %-38s %s"
                     % (cb["id"], route_cell, top_cell, verdict))
    lines.append("-" * 120)
    lines.append("before total: %d/%d   after total: %d/%d   regressions: %d"
                 % (before["summary"]["passed"], before["summary"]["total"],
                    after["summary"]["passed"], after["summary"]["total"],
                    len(regressed)))
    if regressed:
        lines.append("REGRESSED CASES: " + ", ".join(regressed))
    lines.append("")

    path = os.path.join(RESULTS_DIR, "generic_sweep_report.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))
    print("\nwritten: %s" % path)
    return 0 if not regressed else 1


FORCE_OVERWRITE = False


def main():
    global FORCE_OVERWRITE
    ap = argparse.ArgumentParser(
        description="routes-only generic-symptom sweep (see module docstring)")
    ap.add_argument("--out", choices=["before", "after"],
                    help="which snapshot to write (required unless --report)")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing snapshot")
    ap.add_argument("--report", action="store_true",
                    help="render generic_sweep_report.txt from both JSONs")
    args = ap.parse_args()
    if args.report:
        return make_report()
    if not args.out:
        ap.error("--out before|after is required")
    FORCE_OVERWRITE = args.force
    return run_sweep(args.out)


if __name__ == "__main__":
    sys.exit(main())
