import contextlib
import io
import json
import os
import re
import sqlite3
import sys

import chat

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "test_results")
RAW_LOG = os.path.join(RESULTS_DIR, "bug_fix_raw_log.txt")
RESULTS_JSON = os.path.join(RESULTS_DIR, "bug_fix_results.json")

# (label, input, expected condition / country, expected route)
CASES = [
    # ── PROBLEM 1 — trauma questions must reach a database row ──────────
    ("bullet in arm", "My arm is badly injured by a bullet",
     "Gunshot Wound", "body_symptoms"),
    ("shot in the leg", "i got shot in the leg",
     "Gunshot Wound", "body_symptoms"),
    ("stabbed with a knife", "someone was stabbed with a knife",
     "Stab / knife wound", "body_symptoms"),
    ("knifed in the back", "he was knifed in the back",
     "Stab / knife wound", "body_symptoms"),
    ("acid thrown on face", "acid thrown on his face",
     "Acid attack (acid or corrosive thrown at someone)", "body_symptoms"),
    ("drowning", "someone is drowning and not breathing",
     "Near-drowning", "body_symptoms"),
    ("crush injury", "a car crushed my leg and i am trapped",
     "Crush injury trapped under rubble", "body_symptoms"),
    ("lightning strike", "my brother was struck by lightning",
     "Lightning strike", "body_symptoms"),
    # ── PROBLEM 2 — country detection ───────────────────────────────────
    ("pakistani police", "give me the pakistani police number",
     "Pakistan", "emergency_numbers"),
    ("nigeria ambulance", "whats the ambulance number in nigeria",
     "Nigeria", "emergency_numbers"),
    ("netherlands ambulance", "whats the ambulance number in netherlands",
     "Netherlands", "emergency_numbers"),
    ("dubai ambulance", "whats the ambulance number in dubai",
     "United Arab Emirates", "emergency_numbers"),
    ("saudi arabia", "emergency number in saudi arabia",
     "Saudi Arabia", "emergency_numbers"),
    ("united kingdom", "police number in united kingdom",
     "United Kingdom", "emergency_numbers"),
    ("australia", "what number to call in australia",
     "Australia", "emergency_numbers"),
    ("bangladesh", "ambulance in bangladesh",
     "Bangladesh", "emergency_numbers"),
    ("uae", "emergency in uae",
     "United Arab Emirates", "emergency_numbers"),
    # ── over-triage guards: these must NOT be pulled into a CRITICAL row ─
    ("acid reflux", "i have acid reflux and heartburn",
     "Acid reflux / heartburn", "body_symptoms"),
    ("finger in door", "i crushed my finger in the door",
     "Subungual haematoma (nail injury)", "body_symptoms"),
    # ── regression guard on a case that already worked ──────────────────
    ("heart attack", "my chest hurts and left arm is numb",
     "Heart attack (Myocardial Infarction)", "body_symptoms"),
]

TAG_RE = re.compile(r"\[ROUTE: (\S+) \| SOURCE: (\S+)"
                    r"(?: \| MATCHED: (.*?))?\]")


def run_case(user_input):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        chat.chat(user_input)
    out = buf.getvalue()
    m = TAG_RE.search(out)
    route = m.group(1) if m else "?"
    source = m.group(2) if m else "?"
    matched = (m.group(3) or "").strip() if m else ""
    return out, route, source, matched


def row_numbers(row):
    """Every number the verified country row carries."""
    nums = []
    for field in ("police", "ambulance", "fire", "country_code"):
        nums.append(str(row.get(field) or ""))
    try:
        other = json.loads(row.get("other") or "{}")
    except ValueError:
        other = {}
    nums.extend(str(v) for v in other.values())
    digits = set()
    for value in nums:
        for chunk in re.findall(r"\d{2,}", value):
            digits.add(chunk)
    return digits


def main():
    if not os.path.isdir(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    log = []
    passed = failed = 0
    problem1_rows = []
    problem2_rows = []
    json_rows = []

    for label, user_input, expected, expected_route in CASES:
        out, route, source, matched = run_case(user_input)

        db_row = None
        if expected_route == "emergency_numbers":
            db_row = chat.query_emergency_numbers(user_input)
        elif expected_route == "body_symptoms":
            db_row = chat.query_body_symptoms(user_input)

        matched_ok = matched.lower() == expected.lower()
        source_ok = source == "db+llm"

        # For a country question the answer must contain a number that is in
        # the verified row - that is what rules out a hallucinated "911".
        grounded = "n/a"
        if db_row and expected_route == "emergency_numbers":
            numbers = row_numbers(db_row)
            shown = {d for d in re.findall(r"\d{2,}", out)}
            hit = sorted(numbers & shown)
            grounded = "yes" if hit else "NO"
            number_note = "numbers shown: %s | DB numbers: %s" % (
                ", ".join(sorted(shown)) or "none",
                ", ".join(sorted(numbers)) or "none")
        else:
            number_note = ""

        ok = matched_ok and source_ok and grounded in ("yes", "n/a")
        if ok:
            passed += 1
        else:
            failed += 1

        verdict = "PASS" if ok else "FAIL"
        line = ("%-22s %-4s  route=%-18s source=%-8s matched=%-48s "
                "expected=%s" % (label, verdict, route, source,
                                 matched or "(none)", expected))
        print(line)
        if number_note:
            print(" " * 27 + number_note)

        log.append("=" * 70)
        log.append("CASE: %s" % label)
        log.append("INPUT: %s" % user_input)
        log.append("VERDICT: %s" % verdict)
        log.append("EXPECTED condition/country: %s" % expected)
        log.append("ROUTE: %s | SOURCE: %s | MATCHED: %s"
                   % (route, source, matched or "(none)"))
        if db_row:
            log.append("DB ROW: %s" % json.dumps(
                {k: db_row[k] for k in db_row}, ensure_ascii=False))
        if number_note:
            log.append("NUMBER GROUNDING: %s" % number_note)
        log.append("--- USER-VISIBLE OUTPUT ---")
        log.append(out.strip())
        log.append("")

        entry = (label, user_input, matched, expected, source, ok)
        if expected_route == "body_symptoms":
            problem1_rows.append(entry)
        else:
            problem2_rows.append(entry)
        json_rows.append({
            "label": label, "input": user_input, "expected": expected,
            "expected_route": expected_route, "route": route, "source": source,
            "matched": matched, "grounded": grounded, "ok": ok,
            "response": out.strip(),
        })

    print()
    print("body / trauma cases : %d/%d PASS"
          % (sum(1 for e in problem1_rows if e[5]), len(problem1_rows)))
    print("country cases       : %d/%d PASS"
          % (sum(1 for e in problem2_rows if e[5]), len(problem2_rows)))
    print("TOTAL               : %d/%d PASS" % (passed, passed + failed))

    with open(RAW_LOG, "w", encoding="utf-8") as fh:
        fh.write("RAW LOG - bug fix verification (model %s)\n" % chat.MODEL)
        fh.write("\n".join(log))
        fh.write("\nTOTAL: %d/%d PASS\n" % (passed, passed + failed))
    with open(RESULTS_JSON, "w", encoding="utf-8") as fh:
        json.dump({"model": chat.MODEL, "cases": json_rows,
                   "passed": passed, "failed": failed}, fh, indent=1)
    print("raw log -> %s" % RAW_LOG)
    print("results  -> %s" % RESULTS_JSON)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
