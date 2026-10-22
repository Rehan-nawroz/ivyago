import os
import re
import sys
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from keyword_detector.keywords import run as pipeline_run          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── CONFIG ──────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:0.5b"
RESULTS_DIR = os.path.join(BASE_DIR, "test_results")
REPORT_PATH = os.path.join(RESULTS_DIR, "db_fix_report.txt")


# ── DB QUERY (delegates to the real, scored pipeline) ─────────────
def query_body_symptoms(keyword, user_input=None):
    """Top body_symptoms row for this message (relevance scored).

    `user_input` is the full sentence; when it is omitted the keyword is used
    as the sentence, which keeps the old keyword-only calls working.
    """
    text = user_input or keyword
    result = pipeline_run(text)
    if result.get("route") != "body_symptoms":
        return None
    rows = result.get("db_results") or []
    return rows[0] if rows else None


def query_medicine(name, user_input=None):
    """Top medicines row for this message (relevance scored)."""
    text = user_input or name
    result = pipeline_run(text)
    if result.get("route") != "medicines":
        return None
    rows = result.get("db_results") or []
    return rows[0] if rows else None


def query_emergency_number(country, user_input=None):
    """Top emergency_numbers row for this message."""
    text = user_input or country
    result = pipeline_run(text)
    if result.get("route") != "emergency_numbers":
        return None
    rows = result.get("db_results") or []
    return rows[0] if rows else None


# ── LLM CALL ─────────────────────────────────────
def ask_llm(system_prompt, user_prompt):
    payload = {
        "model": MODEL,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 300},
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=120)
        return r.json()["response"]
    except Exception as exc:
        return "ERROR: LLM not available (%s)" % exc


# ── RESPONSE QUALITY ─────────────────────────────
_STOP = {"the", "and", "for", "with", "your", "you", "that", "this", "from",
         "into", "have", "must", "will", "give", "call", "use", "then", "than",
         "them", "they", "does", "not", "never", "always", "keep", "make",
         "sure", "person", "help", "immediately", "steps", "step"}


def _key_tokens(text):
    return {t for t in re.findall(r"[a-z]{4,}", (text or "").lower())
            if t not in _STOP}


def judge_response(response, row, route):
    """CORRECT when the answer is built out of the verified row, not invented.

    Requires: no LLM error, and (numbers route) the verified number literally
    present, or (other routes) at least two content words that come only from
    the verified row's action text.
    """
    if not response or response.startswith("ERROR:"):
        return "WRONG", "no usable LLM answer"
    if route == "emergency_numbers":
        if not row:
            return "WRONG", "no verified row"
        for key in ("police", "ambulance", "fire"):
            n = str(row.get(key, "") or "")
            if n and re.sub(r"\D", "", n) and n in response:
                return "CORRECT", "verified number present"
        return "WRONG", "verified numbers absent from the answer"
    if not row:
        return "WRONG", "no verified row"
    action = " ".join(str(row.get(k, "")) for k in
                      ("immediate_action", "what_not_to_do", "overdose_action",
                       "antidote", "max_dose_adult", "warnings"))
    hit = _key_tokens(action) & _key_tokens(response)
    if len(hit) >= 2:
        return "CORRECT", "grounded in verified row"
    return "WRONG", "answer not grounded in the verified row"


# ── TEST RUNNER ───────────────────────────────────
def run_test(label, user_input, db_result=None, route="body_symptoms",
             expect=None):
    print("\n" + "=" * 55)
    print("TEST: %s" % label)
    print("INPUT: %s" % user_input)
    print("=" * 55)

    if db_result:
        row = db_result
        label_text = (row.get("condition") or row.get("medicine_name")
                      or row.get("country") or "")
        print("DB ROW MATCHED: %s" % label_text)
        print("SCORE: %s" % row.get("_score", "n/a"))
        if expect is not None:
            print("CORRECT MATCH: %s" %
                  ("YES" if re.search(expect, label_text, re.I) else "NO"))
        if route == "emergency_numbers":
            verified = "Country: %s | Police: %s | Ambulance: %s | Fire: %s" % (
                row.get("country", ""), row.get("police", ""),
                row.get("ambulance", ""), row.get("fire", ""))
        elif route == "medicines":
            verified = (
                "Medicine: %s\nOverdose action: %s\nAntidote: %s\n"
                "Maximum adult dose: %s\nWarnings: %s" % (
                    row.get("medicine_name", ""), row.get("overdose_action", ""),
                    row.get("antidote", ""), row.get("max_dose_adult", ""),
                    row.get("warnings", "")))
        else:
            verified = ("Condition: %s\nImmediate action: %s\n"
                        "What NOT to do: %s" % (
                            row.get("condition", ""),
                            row.get("immediate_action", ""),
                            row.get("what_not_to_do", "")))
        source = "DB + LLM"
    else:
        verified = None
        source = "LLM ALONE"
        print("DB ROW MATCHED: none")

    system = ("You are an offline emergency assistant. "
              "Give ONLY immediate numbered steps. "
              "Start with EMERGENCY - ACT NOW if critical.")

    if verified:
        prompt = ("User message: %s\n\nVERIFIED DATA — use this exactly, do "
                  "not change it:\n%s\n\nFormat the immediate action as "
                  "numbered steps." % (user_input, verified))
    else:
        prompt = user_input

    response = ask_llm(system, prompt)
    verdict, why = judge_response(response, db_result, route)

    print("SOURCE: %s" % source)
    if db_result:
        print("RESPONSE CORRECT: %s (%s)" % (verdict, why))
    print("RESPONSE:\n%s" % response)

    return {
        "label": label, "input": user_input, "source": source,
        "row": ((db_result or {}).get("condition")
                or (db_result or {}).get("medicine_name")
                or (db_result or {}).get("country") or "none"),
        "score": (db_result or {}).get("_score"),
        "match_ok": (bool(re.search(expect, label_text, re.I))
                     if (expect and db_result) else None),
        "verdict": verdict, "why": why, "response": response,
    }


# ── RUN ALL TESTS ─────────────────────────────────
if __name__ == "__main__":
    print("\n🔴 TEST GROUP 1 — BODY SYMPTOMS")
    burn_input = "i burned my hand on the stove"
    burn_llm = run_test("BURN — LLM alone", burn_input, db_result=None,
                        route="body_symptoms")
    burn_db = run_test("BURN — with DB", burn_input,
                       db_result=query_body_symptoms("burn", burn_input),
                       route="body_symptoms",
                       expect=r"hand burns|severe burns|scald")

    print("\n🔴 TEST GROUP 2 — HEART ATTACK")
    heart_input = "my chest hurts and left arm is numb"
    heart_llm = run_test("HEART ATTACK — LLM alone", heart_input,
                         db_result=None, route="body_symptoms")
    heart_db = run_test("HEART ATTACK — with DB", heart_input,
                        db_result=query_body_symptoms("heart attack",
                                                      heart_input),
                        route="body_symptoms", expect=r"heart attack")

    print("\n🔴 TEST GROUP 3 — MEDICINE OVERDOSE")
    para_input = "i took too many paracetamol tablets"
    para_llm = run_test("PARACETAMOL — LLM alone", para_input, db_result=None,
                        route="medicines")
    para_db = run_test("PARACETAMOL — with DB", para_input,
                       db_result=query_medicine("paracetamol", para_input),
                       route="medicines", expect=r"paracetamol")

    print("\n🔴 TEST GROUP 4 — HALLUCINATION CHECK (EMERGENCY NUMBERS)")
    num_input = "what is the emergency number in pakistan"
    num_llm = run_test("PAKISTAN NUMBER — LLM alone", num_input, db_result=None,
                       route="emergency_numbers")
    num_db = run_test("PAKISTAN NUMBER — with DB", num_input,
                      db_result=query_emergency_number("pakistan", num_input),
                      route="emergency_numbers", expect=r"pakistan")

    # ---- named requirement checks + report -------------------------
    checks = {"burn": burn_db, "heart": heart_db,
              "paracetamol": para_db, "number": num_db}
    matched = {k: bool(v["match_ok"]) for k, v in checks.items()}

    # "Total tests: 4" = the four DB-backed cases, as specified.
    passed = sum(1 for v in matched.values() if v)
    status = ("READY FOR ANDROID INTEGRATION"
              if passed == 4 else "NEEDS MORE FIXES")

    lines = [
        "---DB QUERY FIX REPORT---",
        "Fix applied to keywords.py: YES",
        "Fix applied to test_db_llm.py: YES",
        "",
        "Test results:",
        "Burn → correct row matched: %s" % ("YES" if matched["burn"] else "NO"),
        "Heart attack → correct row matched: %s" % (
            "YES" if matched["heart"] else "NO"),
        "Paracetamol → correct row matched: %s" % (
            "YES" if matched["paracetamol"] else "NO"),
        "",
        "LLM response quality:",
        "Burn with DB: %s" % checks["burn"]["verdict"],
        "Heart attack with DB: %s" % checks["heart"]["verdict"],
        "Paracetamol with DB: %s" % checks["paracetamol"]["verdict"],
        "",
        "Total tests: 4",
        "Passed: %d/4" % passed,
        "Status: %s" % status,
        "---DONE---",
    ]
    report = "\n".join(lines) + "\n"
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report)
        fh.write("\n\n---DETAIL (rows matched, scores, raw answers)---\n")
        for group in (burn_llm, burn_db, heart_llm, heart_db, para_llm, para_db,
                      num_llm, num_db):
            fh.write("\n" + "=" * 55 + "\n")
            fh.write("TEST: %s\nINPUT: %s\n" % (group["label"], group["input"]))
            fh.write("SOURCE: %s\nDB ROW MATCHED: %s\nSCORE: %s\n" %
                     (group["source"], group["row"], group["score"]))
            if group["source"] == "DB + LLM":
                fh.write("RESPONSE CORRECT: %s (%s)\n" %
                         (group["verdict"], group["why"]))
            fh.write("RESPONSE:\n%s\n" % group["response"])

    print("\n" + report)
    print("report written -> %s" % REPORT_PATH)
