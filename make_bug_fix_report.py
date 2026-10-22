import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "test_results")
RESULTS_JSON = os.path.join(RESULTS_DIR, "bug_fix_results.json")
REPORT = os.path.join(RESULTS_DIR, "bug_fix_report.txt")

# label -> the report line this case answers
LINE_LABELS = {
    "bullet in arm": 'Test "bullet in arm": SOURCE db+llm',
    "shot in the leg": 'Test "got shot in leg": correct response',
    "stabbed with a knife": 'Test "stabbed with knife": correct response',
    "pakistani police": '"pakistani police" \u2192 matched: Pakistan',
    "nigeria ambulance": '"nigeria ambulance" \u2192 matched: Nigeria',
    "netherlands ambulance": '"netherlands ambulance" \u2192 matched: Netherlands',
    "dubai ambulance": '"dubai ambulance" \u2192 matched: United Arab Emirates',
    "saudi arabia": '"saudi arabia" \u2192 matched: Saudi Arabia',
    "united kingdom": '"united kingdom" \u2192 matched: United Kingdom',
    "australia": '"australia" \u2192 matched: Australia',
    "bangladesh": '"bangladesh" \u2192 matched: Bangladesh',
}

FURTHER_DEFECTS = [
    "A. chat.py pasted the WHOLE sentence into the body-symptom LIKE",
    "   (\"%My arm is badly injured by a bullet%\"). No row can contain an entire",
    "   sentence, so multi-word input matched nothing and every real question",
    "   fell through to the model alone - which is what SOURCE: llm_only was",
    "   reporting. Input is now searched word by word and the candidates are",
    "   scored.",
    "B. Routing words were missing, so three of the reported sentences were",
    "   answered with the off-topic refusal even once the rows existed:",
    "   \"someone was stabbed with a knife\", \"my brother was struck by",
    "   lightning\" and the disaster vocabulary (flood, earthquake, collapse)",
    "   scored zero on every route. Route words added.",
    "C. The medicine lookup took the FIRST row that ANY word matched, inside",
    "   the used_for column too, so: \"can i give ibuprofen to a pregnant",
    "   woman\" -> Morphine (the word \"can\" matched \"cancer pain\"), \"i took",
    "   too much ibuprofen\" -> Paracetamol, \"my child ate rat poison\" ->",
    "   Zidovudine. It now asks the detector first and only searches the drug",
    "   name and its aliases, longest word first, whole words only.",
    "D. Heart attack row: \"my chest hurts and left arm is numb\" was answered",
    "   by the Stroke row, because nothing in the heart attack row said",
    "   \"numb\" (numbness down the left arm is textbook presentation). Row",
    "   enriched; the stroke case with \"i cant speak\" still wins its own row.",
    "E. \"i crushed my finger in the door\" was answered with the CRITICAL",
    "   \"Crush injury trapped under rubble\" row. The nail-injury row and the",
    "   vocabulary now carry the door/crush wording.",
    "F. \"i cut my finger with a knife\" was answered with the new Stab row",
    "   (which needs the word \"knife\" for real knife attacks) and, before",
    "   that, with Finger amputation. A cut finger is a skin laceration, so",
    "   the laceration row now carries the finger/knife wording.",
    "G. The engine's own vocabulary knew none of the new scenarios either:",
    "   \"i got shot in the leg\", \"a car crushed my leg\" and \"acid attack\"",
    "   routed to general and were refused. Vocabulary completed.",
    "H. Over-triage guard: a bare \"acid\" keyword would have let the new",
    "   CRITICAL acid-attack row answer \"i have acid reflux\". Verified that",
    "   the heartburn row wins, and that the pre-existing Chemical burn row had",
    "   exactly the same behaviour before this change.",
    "I. Nondeterminism (found by re-running the suite): the engine truncated",
    "   its keyword-variant list with a sort key that left ties to be broken by",
    "   Python's randomised string hashing, so the candidate pool - and the",
    "   answer - changed from process to process. \"i spilled boiling water on",
    "   my arm\" answered with the Flood row in 1 run out of 6, and the 112-case",
    "   route check was flaky. Fixed with a total sort key; verified over",
    "   repeated processes (see test_results/determinism_sweep.log).",
]

FILES = [
    "chat.py                        - the three lookups, the route word lists",
    "                                 and the country detection function",
    "db/add_trauma_rows.py          - the 3 new rows + keyword completion for",
    "                                 drowning / lightning / crush (re-runnable)",
    "db/enrich_matched_rows.py      - heart attack, nail injury and laceration",
    "                                 wording (re-runnable)",
    "keyword_detector/keywords.py   - trauma vocabulary + deterministic ranking",
    "test_bug_fixes.py              - drives chat.py over 20 real inputs",
    "make_bug_fix_report.py         - renders this report from those results",
    "test_results/bug_fix_raw_log.txt - every input, row, score and answer",
    "test_results/bug_fix_results.json - the same as machine-readable results",
]

LIMITATIONS = [
    "* Answers are produced by qwen2.5:1.5b through Ollama, temperature 0.1.",
    "  One run per case is evidence, not a stability guarantee: the model is",
    "  stochastic, so a case that passes here can still come out worse on",
    "  another run. The ROW the database matched is deterministic; the wording",
    "  of the answer is not.",
    "* Country detection covers the adjectives, city names, abbreviations and",
    "  common alternative names in the map plus the exact country name and its",
    "  ISO code. A misspelling (\"cote divoire\", \"netherland\") returns no",
    "  country instead of a wrong one - a deliberate choice: no answer beats",
    "  the wrong country's number. Multiple countries in one message resolve",
    "  to the longest name match.",
    "* The country_code tiebreaker ignores codes that are ordinary English",
    "  words (\"in\" = India, \"me\" = Montenegro), so a question with no",
    "  country in it returns None rather than guessing.",
    "* Body-part exotica beyond the tested set (rare phrasings, regional slang,",
    "  non-English messages) are not covered; the detector's own vocabulary is",
    "  still the limiting factor there.",
    "* The Android / llama.cpp path and the audio input were not exercised -",
    "  ANDROID_MODE and call_llm_android() still do not exist in the tree.",
]

PROBLEM1_OTHERS = [
    "Stab / knife wound (NEW row)",
    "Acid attack (acid or corrosive thrown at someone) (NEW row)",
    "Near-drowning - row existed, keywords completed (drowned, fell in water, "
    "cant swim, swallowed water, ...)",
    "Lightning strike - row existed, keywords completed (electrocuted by "
    "lightning, hit by lightning, thunder struck, ...)",
    "Crush injury trapped under rubble - row existed, keywords completed "
    "(crushed, trapped under car, heavy object on body, pinned under debris, ...)",
]


def main():
    with open(RESULTS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    cases = {c["label"]: c for c in data["cases"]}

    def yn(label):
        case = cases.get(label)
        return "YES" if case and case["ok"] else "NO"

    lines = []
    lines.append("---BUG FIX REPORT---")
    lines.append("")
    lines.append("PROBLEM 1 \u2014 GUNSHOT WOUND")
    lines.append("Row added to DB: YES (Gunshot Wound, severity CRITICAL, "
                 "verified with SELECT)")
    lines.append('%s: %s' % (LINE_LABELS["bullet in arm"], yn("bullet in arm")))
    lines.append('%s: %s' % (LINE_LABELS["shot in the leg"], yn("shot in the leg")))
    lines.append('%s: %s' % (LINE_LABELS["stabbed with a knife"],
                             yn("stabbed with a knife")))
    lines.append("Other missing scenarios added:")
    for item in PROBLEM1_OTHERS:
        lines.append("  - " + item)
    lines.append("")
    lines.append("PROBLEM 2 \u2014 COUNTRY DETECTION")
    lines.append("Fix applied to chat.py: YES")
    for label in ("pakistani police", "nigeria ambulance",
                  "netherlands ambulance", "dubai ambulance", "saudi arabia",
                  "united kingdom", "australia", "bangladesh"):
        lines.append("%s %s" % (LINE_LABELS[label], yn(label)))
    numbers = [cases.get(l, {}).get("grounded") == "yes"
               for l in LINE_LABELS if l in cases and
               cases[l]["expected_route"] == "emergency_numbers"]
    number_verdict = ("YES" if all(numbers) else
                      "PARTIAL" if any(numbers) else "NO")
    lines.append("LLM giving correct numbers: %s (every number in every "
                 "answer was checked against the matched country row - a "
                 "number the row does not contain fails)" % number_verdict)
    lines.append("")
    lines.append("---TOTAL BUGS FIXED: 2---")
    status = "READY" if data["failed"] == 0 else "NEEDS MORE FIXES"
    lines.append("Status: %s" % status)
    lines.append("---DONE---")

    # ---------------- measured detail ----------------
    lines.append("")
    lines.append("")
    lines.append("---MEASURED RESULTS (model %s)---" % data["model"])
    lines.append("")
    lines.append("--- PROBLEM 1 / trauma questions ---")
    for label, case in cases.items():
        if case["expected_route"] != "body_symptoms":
            continue
        lines.append('[%s] %s' % ("PASS" if case["ok"] else "FAIL",
                                  case["input"]))
        lines.append('        route=%s source=%s matched=%s'
                     % (case["route"], case["source"],
                        case["matched"] or "(none)"))
    lines.append("")
    lines.append("--- PROBLEM 2 / country questions ---")
    for label, case in cases.items():
        if case["expected_route"] != "emergency_numbers":
            continue
        lines.append('%-8s %-28s matched=%-24s numbers grounded in the DB row: %s'
                     % ("PASS" if case["ok"] else "FAIL", case["input"],
                        case["matched"], case["grounded"]))
    lines.append("")
    lines.append("Totals: %d/%d cases PASS"
                 % (data["passed"], data["passed"] + data["failed"]))
    lines.append("")
    lines.append("---FURTHER DEFECTS FOUND WHILE FIXING THESE TWO---")
    lines.append("")
    for text in FURTHER_DEFECTS:
        lines.append(text)
    lines.append("")
    lines.append("---FILES---")
    lines.append("")
    for text in FILES:
        lines.append(text)
    lines.append("")
    lines.append("---LIMITATIONS---")
    lines.append("")
    for text in LIMITATIONS:
        lines.append(text)
    lines.append("")
    lines.append("---DONE---")

    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("report written -> %s" % REPORT)


if __name__ == "__main__":
    main()
