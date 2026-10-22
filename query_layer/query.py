"""
query_layer/query.py — the final bridge of the offline emergency assistant.

Position in the full pipeline:

    user types a message
        |
        v
    keyword_detector/keywords.py :: run(user_input)
        returns route + severity_hint + db_results (verified SQLite rows)
        |
        v
    query_layer/query.py :: answer(user_input)          <-- THIS FILE
        1. build_system_prompt(severity)   -> behaviour rules for the LLM
        2. build_user_prompt(...)          -> injects the verified DB data
        3. call_llm(system, user)          -> Qwen via Ollama, temp 0.1
        4. build_banner(severity)          -> status line shown to the user
        |
        v
    app displays banner + response

Design guarantees:
    * temperature stays at 0.1 so the LLM cannot get creative with
      medical facts -- the DB rows are the single source of truth.
    * the LLM is NEVER called without a system prompt.
    * DB data is ALWAYS injected into the user prompt when the detector
      found any -- the LLM never guesses what the detector already knew.
    * every failure mode (Ollama down, timeout, bad payload) degrades to
      a friendly "ERROR: ..." string. A traceback never reaches the user.
"""

# ----------------------------------------------------------------------
# Imports -- Python standard library + requests (per spec).
#
# NOTE: direct database access lives in keyword_detector/keywords.py,
# which resolves all DB paths with os.path relative to ITS OWN file
# location, so the whole pipeline works on any machine. This module
# never opens a database itself; sqlite3/json remain part of the
# specified module interface.
# ----------------------------------------------------------------------
import os
import json
import re
import sqlite3
import sys
import requests
from collections import Counter
from pathlib import Path

# Make the sibling keyword_detector package importable no matter which
# directory the app is launched from.
sys.path.append(str(Path(__file__).parent.parent))
from keyword_detector.keywords import run as detect_and_query

# ----------------------------------------------------------------------
# Ollama configuration
# ----------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:0.5b"
OLLAMA_TIMEOUT = 30  # seconds before giving up on the LLM


def build_system_prompt(severity: str) -> str:
    if severity == "CRITICAL":
        return (
            "You are an offline emergency assistant.\n"
            "A life may be at risk RIGHT NOW.\n"
            "Give ONLY the immediate actions the person must take.\n"
            "Use simple short sentences.\n"
            "Number every step.\n"
            "Start your response with: EMERGENCY - ACT NOW\n"
            "Do not explain medical theory.\n"
            "Do not suggest calling a doctor if the person clearly cannot.\n"
            "Do not add disclaimers.\n"
            "Speak directly to the person in front of you."
        )
    if severity == "URGENT":
        return (
            "You are an offline emergency assistant.\n"
            "This situation needs prompt attention.\n"
            "Give clear step by step instructions.\n"
            "Number every step.\n"
            "Keep language simple.\n"
            "End with one sentence on when to seek further help."
        )
    if severity == "MODERATE":
        return (
            "You are an offline emergency assistant.\n"
            "Give helpful, clear first aid or medical guidance.\n"
            "Number the steps.\n"
            "Keep language simple and calm.\n"
            "End with signs that would make this more serious."
        )
    # UNKNOWN -- and the safe default for any unexpected severity value.
    return (
        "You are an offline emergency assistant.\n"
        "You only help with medical emergencies, first aid,\n"
        "natural disasters, and emergency contact numbers.\n"
        "If the question is outside these topics respond with\n"
        "exactly this:\n"
        "I am an offline emergency assistant. I can only help\n"
        "with medical emergencies, first aid, and disaster\n"
        "situations.\n"
        "Keep all answers simple and clear."
    )


_OVERDOSE_WORDS = (
    "overdose", "overdosed", "too many", "too much", "whole bottle",
    "double dose", "swallowed", "took extra", "poison", "poisoning",
    "accidental", "extra pills", "extra tablets",
)

_SAFETY_WORDS = (
    "safe", "safety", "can i take", "can i give", "should i take", "is it ok",
    "is it okay", "pregnancy", "pregnant", "breastfeeding", "side effect",
    "side effects", "interaction", "how much", "how many", "max dose",
    "maximum dose", "dose", "dosage", "expired", "out of date", "still good",
    "with alcohol", "warning", "warnings", "allergic",
)


def _pregnancy_text(value: str) -> str:
    """Render the short stored pregnancy value as an unambiguous statement.
    The column holds only 'Yes' / 'No' / 'Consult doctor'; a bare "No" next to
    the label "Safe in pregnancy" was inverted by the model into "Yes, safe in
    pregnancy" for ibuprofen, so the value is spelled out instead."""
    text = (value or "").strip()
    low = text.lower()
    if low == "no":
        return "NOT safe in pregnancy (verified) -- avoid."
    if low == "yes":
        return "Considered safe in pregnancy (verified)."
    if low in ("consult doctor", "consult", "ask doctor"):
        return "Not established as safe -- consult a doctor."
    return text


def _is_overdose_question(lowered_input: str) -> bool:
    return any(w in lowered_input for w in _OVERDOSE_WORDS)


_EXPIRY_WORDS = (
    "expired", "expire", "expiry", "out of date", "still good",
    "past its date", "old medicine", "old tablets",
)

# The verified rows almost never carry an "expiry" field, so the model was left
# to invent one -- "i took expired antibiotics" produced the three fragments
# "Take expired antibiotics. Do NOT use expired tetracycline. Supportive care."
# This standard offline rule gives it something true to answer with instead.
_EXPIRY_INSTRUCTION = (
    "The user is asking about an EXPIRED medicine. Do not say the medicine "
    "is still in date. Answer directly and "
    "briefly. If the verified Warnings above mention expiry, use them. Then "
    "state this standard rule in your own simple words: after its expiry date "
    "a medicine usually loses strength rather than becoming poisonous, but do "
    "not take expired antibiotics, eye drops, insulin, liquid medicines or "
    "anything that has changed colour or smell; never take a double dose to "
    "catch up; take it to a pharmacy for safe disposal and get a fresh supply. "
    "Do NOT give overdose, poisoning or emergency steps unless the user "
    "described an overdose. Number the points."
)


def _is_safety_question(lowered_input: str) -> bool:
    return any(w in lowered_input for w in _SAFETY_WORDS)


def _is_expiry_question(lowered_input: str) -> bool:
    return any(w in lowered_input for w in _EXPIRY_WORDS)


def build_user_prompt(user_input: str, db_results: list, route: str) -> str:
    top_result = db_results[0] if db_results else {}

    if route == "body_symptoms" and db_results:
        return f"""User message: {user_input}

VERIFIED EMERGENCY DATA (use this, do not change it):
Condition: {top_result.get('condition', '')}
Severity: {top_result.get('severity', '')}
Immediate action: {top_result.get('immediate_action', '')}
What NOT to do: {top_result.get('what_not_to_do', '')}

Using the verified data above, give the user clear step by step instructions. Do not add or change any medical facts. Format the immediate action as numbered steps."""

    if route == "medicines" and db_results:
        # A drug-safety question ("is ibuprofen safe in pregnancy") must not be
        # answered with overdose or poisoning steps just because the row data
        # holds them -- the instruction sent to the model has to match the
        # question that was actually asked.
        lowered = user_input.lower()
        if _is_overdose_question(lowered):
            instruction = (
                "The person has taken too much. Using the verified data above, "
                "give the immediate steps. Format the overdose action as "
                "numbered steps. Do not change any medical facts."
            )
        elif _is_expiry_question(lowered):
            instruction = _EXPIRY_INSTRUCTION
        elif _is_safety_question(lowered):
            instruction = (
                "Answer the user's safety question directly and briefly using "
                "only the fields above. Use the exact field that was asked "
                "about (Pregnancy / Maximum adult dose / Maximum child dose / "
                "Warnings) and repeat its meaning faithfully. NEVER say a "
                "medicine is safe in pregnancy unless the verified pregnancy "
                "line says it is safe. Do NOT give overdose, poisoning or "
                "emergency steps unless the user described an overdose."
            )
        else:
            instruction = (
                "Using the verified data above, clearly explain what the "
                "person should know right now. Do not change any medical facts."
            )
        return f"""User message: {user_input}

VERIFIED MEDICINE DATA (use this, do not change it):
Medicine: {top_result.get('medicine_name', '')}
Also known as: {top_result.get('aliases', '')}
Overdose symptoms: {top_result.get('overdose_symptoms', '')}
Overdose action: {top_result.get('overdose_action', '')}
Antidote: {top_result.get('antidote', '')}
Maximum adult dose: {top_result.get('max_dose_adult', '')}
Pregnancy (verified): {_pregnancy_text(top_result.get('safe_in_pregnancy', ''))}
Maximum child dose: {top_result.get('max_dose_child', '')}
Warnings: {top_result.get('warnings', '')}

{instruction}"""

    if route == "emergency_numbers" and db_results:
        number_lines = "\n".join(
            f"Country: {row.get('country', '')} | Police: {row.get('police', '')} | "
            f"Ambulance: {row.get('ambulance', '')} | Fire: {row.get('fire', '')}"
            for row in db_results
        )
        return f"""User message: {user_input}

VERIFIED EMERGENCY NUMBERS (use exactly these numbers, do not change or guess any number):
{number_lines}

Tell the user exactly which numbers to call based on their situation. Keep every number with the service it is listed under (police / ambulance / fire) - never move a number to a different service, and never add a service that is not in the list. Never guess a number not in this list."""

    # route == "general", or a DB-backed route that returned no rows.
    return f"""User message: {user_input}

Answer based on your emergency knowledge only.
If this is not an emergency topic, politely refuse."""


def call_llm(system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,   # keep the LLM factual, never creative
            "top_p": 0.9,
            "num_predict": 512,
        },
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response")
        if not isinstance(text, str):
            # Ollama answered, but without a "response" field (e.g. an
            # error payload such as "model not found").
            return "ERROR: Could not generate response. Please try again."
        return text
    except requests.exceptions.Timeout:
        return "ERROR: LLM took too long to respond."
    except requests.exceptions.ConnectionError:
        return "ERROR: LLM not running. Start Ollama with: ollama run qwen2.5:0.5b"
    except (requests.exceptions.RequestException, ValueError, KeyError):
        return "ERROR: Could not generate response. Please try again."
    except Exception:
        # Absolute last resort -- the user must never see a traceback.
        return "ERROR: Could not generate response. Please try again."


# Returned by clean_response when the model produced nothing usable.
_EMPTY_REPLY = "Please describe your emergency and I will provide guidance."


def clean_response(text: str) -> str:
    # STEP 1 -- SPLIT INTO LINES (trim, drop empties)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # STEP 2 -- DETECT AND REMOVE REPEATED LINES
    def _clean_for_compare(line: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", line.lower())

    seen = set()
    kept_lines = []
    for line in lines:
        key = _clean_for_compare(line)
        if key in seen:
            continue
        seen.add(key)
        kept_lines.append(line)

    # STEP 3 -- DETECT REPEATED PHRASES WITHIN A LINE
    # e.g. "Call 911. Call 911. Call 911." -> "Call 911."
    final_lines = []
    for line in kept_lines:
        sentences = [s.strip() for s in line.split(". ")]
        unique = []
        seen_sent = set()
        for s in sentences:
            skey = _clean_for_compare(s)
            if skey in seen_sent:
                continue
            seen_sent.add(skey)
            unique.append(s)
        out_line = ". ".join(unique)
        # If the line ended with a period that belonged to a dropped repeat,
        # restore it ("Call 911. Call 911. Call 911." -> "Call 911.").
        if unique and line.rstrip().endswith(".") and not out_line.endswith("."):
            out_line += "."
        final_lines.append(out_line)

    # STEP 4 -- REBUILD AND RETURN
    cleaned = "\n".join(final_lines)
    if len(cleaned) < 10:
        # Nothing usable came back (the model emitted only whitespace or one
        # deduplicated fragment). This sentinel is recognised in answer(),
        # which then falls back to the verified DB text -- answering the
        # Nigeria question with "Please describe your emergency" while the
        # verified 112 was sitting unused in db_results was a real bug.
        cleaned = _EMPTY_REPLY
    return cleaned


def build_banner(severity: str) -> str:
    if severity == "CRITICAL":
        return "🔴 CRITICAL EMERGENCY — FOLLOW STEPS IMMEDIATELY"
    if severity == "URGENT":
        return "🟡 URGENT — NEEDS ATTENTION SOON"
    if severity == "MODERATE":
        return "🟢 MODERATE — MANAGEABLE SITUATION"
    return "ℹ️  GENERAL ASSISTANCE"


_PROMPT_ECHO_MARKERS = (
    "if this is not an emergency topic",
    "politely refuse",
    "if the question is outside these topics",
    "respond with exactly this",
    "review the verified data",
    "identify the condition",
    "identify the severity",
    "identify the immediate action",
    "determine the immediate action",
    "determine the severity",
    "using the verified data above",
    "do not add or change any medical facts",
    "do not change any medical facts",
    "format the immediate action as numbered steps",
    "use exactly these numbers",
    "never guess a number not in this list",
    "based on your emergency knowledge only",
    "keep every number with the service",
    "never move a number to a different service",
)

# Shown when the model echoed an instruction AND there is no verified row to
# fall back on, so the user never reads a prompt instruction as an answer.
_ECHO_SAFE_REPLY = (
    "I am an offline emergency assistant. Please describe the emergency "
    "and I will give you the immediate steps."
)


def _echoes_prompt(text: str) -> bool:
    """True when the model returned prompt instructions, not an answer."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _PROMPT_ECHO_MARKERS)


def _looks_degenerate(text: str) -> bool:
    """True when the answer is a repetition loop rather than an answer. The
    0.5B model sometimes loops one clause across the whole reply, e.g. "The
    maximum adult dose is NOT safe in pregnancy (verified)." repeated three
    times -- a phrase repeat that clean_response's line dedup cannot see.
    Numbered lists defeat the duplicate-line test too: the answer to
    "emergency number in united states" was "4. Medical: 911 | 5. Medical:
    911 | 6. Medical: 911 ...", where every line differs only by its number."""
    body = (text or "").strip()
    if not body:
        return True
    lines = [ln.strip() for ln in body.splitlines() if len(ln.strip()) > 20]
    if len(lines) >= 3 and len(set(lines)) * 2 <= len(lines):
        return True
    # Same test again with the leading list numbering and punctuation removed,
    # so "5. Medical: 911" and "6. Medical: 911" count as the same line.
    stripped = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        content = re.sub(r"^[\d]+[.):\-\s]+", "", line)
        content = re.sub(r"[^a-z]", "", content.lower())
        if len(content) >= 3:
            stripped.append(content)
    if len(stripped) >= 4:
        if Counter(stripped).most_common(1)[0][1] >= 3:
            return True
    words = body.lower().split()
    counts = {}
    for i in range(len(words) - 4):
        phrase = " ".join(words[i:i + 5])
        counts[phrase] = counts.get(phrase, 0) + 1
        if counts[phrase] >= 3:
            return True
    return False


_PREGNANCY_MARKERS = ("pregnan", "breastfeed", "breast-feed", "expecting")
_POSITIVE_SAFETY_CLAIMS = (
    "safe in pregnancy", "safe during pregnancy", "safe for pregnancy",
    "safe to take during pregnancy", "safe to use in pregnancy",
    "safe for the baby", "safe to give",
)
# An answer that already denies safety is left alone, however it is phrased.
# A bare "consult a doctor" is NOT a denial: the model answered "Yes, you can
# give Ibuprofen to a pregnant woman. However ... Always consult a healthcare
# professional" -- an affirmative claim with a soft tail that must not be able
# to switch this guard off.
_SAFETY_DENIALS = (
    "not safe", "unsafe", "avoid", "do not", "don't", "dont", "never",
    "no evidence", "not recommended", "not established", "not advised",
    "contraindicated", "should not be used", "must not",
)


def _inverts_safety_verdict(user_input: str, db_results: list, route: str,
                            response: str) -> bool:
    """True when the answer claims a medicine is safe although the verified
    row says it must not be used in pregnancy."""
    if route != "medicines" or not db_results:
        return False
    lowered_input = (user_input or "").lower()
    if not any(m in lowered_input for m in _PREGNANCY_MARKERS):
        return False
    value = (db_results[0].get("safe_in_pregnancy") or "").strip().lower()
    if value not in ("no", "consult doctor", "consult", "ask doctor"):
        return False
    lowered = (response or "").lower()
    if any(d in lowered for d in _SAFETY_DENIALS):
        return False
    if any(c in lowered for c in _POSITIVE_SAFETY_CLAIMS):
        return True
    # "Can give Ibuprofen to a pregnant woman." never says the word "safe",
    # so a bare permission sentence about a pregnancy is treated the same way.
    if (re.search(r"\b(can|may|should)\s+(take|give|use|have)\b", lowered)
            and any(m in lowered for m in _PREGNANCY_MARKERS)):
        return True
    return False


def build_db_fallback(db_results: list, route: str) -> str:
    """Verified, database-only answer built straight from the top row.
    Used whenever the LLM output is unusable, so the checked data is never
    thrown away because of a bad model response."""
    if not db_results:
        return ""
    row = db_results[0]
    if route == "emergency_numbers":
        return ("Call {country}: police {police}, ambulance {ambulance}, "
                "fire {fire}.").format(
            country=row.get("country", ""),
            police=row.get("police", ""),
            ambulance=row.get("ambulance", ""),
            fire=row.get("fire", ""),
        )
    if route == "medicines":
        lines = [str(row.get("medicine_name", ""))]
        if row.get("safe_in_pregnancy"):
            lines.append("Pregnancy: %s" % _pregnancy_text(row["safe_in_pregnancy"]))
        if row.get("max_dose_adult"):
            lines.append("Maximum adult dose: %s" % row["max_dose_adult"])
        if row.get("overdose_action"):
            lines.append("If too much was taken: %s" % row["overdose_action"])
        if row.get("warnings"):
            lines.append("Warnings: %s" % row["warnings"])
        return "\n".join(lines)
    lines = []
    if row.get("condition"):
        lines.append("Condition: %s" % row["condition"])
    if row.get("immediate_action"):
        lines.append("Do this now: %s" % row["immediate_action"])
    if row.get("what_not_to_do"):
        lines.append("Do NOT: %s" % row["what_not_to_do"])
    return "\n".join(lines)


def answer(user_input: str) -> dict:
    # Step 1 -- detect route + severity and fetch verified DB rows.
    detection = detect_and_query(user_input)
    route = detection.get("route", "general")
    severity_hint = detection.get("severity_hint", "UNKNOWN")
    critical_override = detection.get("critical_override", False)
    db_results = detection.get("db_results", [])
    db_result_count = detection.get("db_result_count", 0)

    # SAFETY CHECK -- never hard-refuse if there is any chance this is an
    # emergency related question. Off-topic chatter gets an instant local
    # refusal (no LLM call); anything that mentions an emergency word is
    # handed to the LLM, or forced onto the emergency_numbers route as a
    # fallback so a possible emergency is never bounced with a refusal.
    emergency_related = [
        "emergency", "number", "call", "ambulance",
        "police", "fire", "help", "rescue", "hospital",
        "doctor", "hurt", "pain", "bleeding", "burn",
        "accident", "disaster", "flood", "earthquake",
        "medicine", "pill", "tablet", "overdose", "poison",
        "breathe", "breathing", "unconscious", "attack",
        "stroke", "choking", "drowning", "injured", "injury",
        "baby", "child", "pregnant", "blood", "wound",
        "broken", "fracture", "allergy", "swallowed",
    ]

    user_lower = user_input.lower()

    # If ANY emergency word is in the input -> do NOT hard refuse,
    # let the LLM handle it.
    is_emergency_related = any(
        word in user_lower for word in emergency_related
    )

    if detection["route"] == "general" and not is_emergency_related:
        return {
            "banner": "\u2139\ufe0f  GENERAL ASSISTANCE",
            "response": "I am an offline emergency assistant. "
                        "I can only help with medical emergencies, "
                        "first aid, natural disasters, and emergency "
                        "contact numbers. Please describe your "
                        "emergency and I will help you.",
            "route": "general",
            "severity": "UNKNOWN",
            "critical_override": False,
            "db_results_used": 0,
            "source": "hardcoded_refusal",
        }

    # If emergency related but route is still general -> force route to
    # emergency_numbers as a safety fallback.
    if detection["route"] == "general" and is_emergency_related:
        detection["route"] = "emergency_numbers"
        detection["severity_hint"] = "URGENT"
        # Keep the local variables in sync with the mutated detection.
        route = detection["route"]
        severity_hint = detection["severity_hint"]

    # Step 2 -- build prompts (system prompt is mandatory, never empty).
    system_prompt = build_system_prompt(severity_hint)
    user_prompt = build_user_prompt(user_input, db_results, route)

    # Step 3 -- call the LLM and clean the response before returning it
    # (the 0.5B model can loop-repeat lines or phrases; see clean_response).
    llm_response = clean_response(
        call_llm(system_prompt, user_prompt)
    )

    # Step 3b -- output guard. If the model copied an instruction out of the
    # prompt, or looped one clause into a degenerate answer, use the verified
    # DB text (or the safe reply when there is no row to fall back on).
    if (llm_response == _EMPTY_REPLY
            or _echoes_prompt(llm_response)
            or _looks_degenerate(llm_response)
            or _inverts_safety_verdict(user_input, db_results, route,
                                       llm_response)):
        llm_response = build_db_fallback(db_results, route) or _ECHO_SAFE_REPLY

    # Step 4 -- severity banner for the UI.
    banner = build_banner(severity_hint)

    # Step 5 -- final result package.
    return {
        "banner": banner,
        "response": llm_response,
        "route": route,
        "severity": severity_hint,
        "critical_override": critical_override,
        "db_results_used": db_result_count,
        "source": "db+llm" if db_result_count > 0 else "llm_only",
    }


if __name__ == "__main__":
    # Windows consoles default to cp1252 and cannot print emoji or ✓;
    # force UTF-8 so banners render everywhere.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    test_cases = [
        "my chest hurts and i cant breathe",
        "my friend is not waking up",
        "i took too many paracetamol tablets",
        "there is a fire what number do i call in pakistan",
        "baby is not breathing",
        "i have a deep cut and it wont stop bleeding",
        "someone swallowed bleach",
        "what is the ambulance number in india",
        "i burned my hand on the stove",
        "i feel dizzy and my left arm hurts",
    ]

    # Expected routes from the verified keyword detector self-test.
    expected_routes = {
        "my chest hurts and i cant breathe": "body_symptoms",
        "my friend is not waking up": "body_symptoms",
        "i took too many paracetamol tablets": "medicines",
        "there is a fire what number do i call in pakistan": "emergency_numbers",
        "baby is not breathing": "body_symptoms",
        "i have a deep cut and it wont stop bleeding": "body_symptoms",
        "someone swallowed bleach": "body_symptoms",
        "what is the ambulance number in india": "emergency_numbers",
        "i burned my hand on the stove": "body_symptoms",
        "i feel dizzy and my left arm hurts": "body_symptoms",
    }
    db_backed_routes = {"body_symptoms", "medicines", "emergency_numbers"}

    llm_ok = 0
    db_injected = 0
    crit_count = 0
    routes_ok = 0
    issues = []

    for case in test_cases:
        result = answer(case)
        response = result["response"]

        if not response.startswith("ERROR"):
            llm_ok += 1
        else:
            issues.append(f'LLM error on "{case}": {response}')
        if result["source"] == "db+llm":
            db_injected += 1
        if result["severity"] == "CRITICAL":
            crit_count += 1
        if result["route"] == expected_routes.get(case):
            routes_ok += 1
        else:
            issues.append(
                f'wrong route on "{case}": got {result["route"]}, '
                f"expected {expected_routes.get(case)}"
            )
        if result["route"] in db_backed_routes and result["db_results_used"] == 0:
            issues.append(f'no DB results for db-backed route on "{case}"')

        # Detect degenerate repetition: tiny models can loop the same block
        # until the num_predict cap truncates them mid-sentence. Flag it so
        # the report never claims a looped response was healthy.
        resp_lines = [ln.strip() for ln in response.splitlines() if len(ln.strip()) > 25]
        duplicated = sum(c for c in Counter(resp_lines).values() if c > 1)
        if duplicated >= 5:
            issues.append(f'degenerate repetition in response for "{case}"')

        print("=" * 40)
        print(f'INPUT: "{case}"')
        print(f"BANNER: {result['banner']}")
        print(f"ROUTE: {result['route']}")
        print(f"SEVERITY: {result['severity']}")
        print(f"SOURCE: {result['source']}")
        print(f"DB RESULTS USED: {result['db_results_used']}")
        print("-" * 40)
        print("RESPONSE:")
        print(response)
        print("=" * 40)

    # Write the report next to this file, in the exact required format.
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_report.txt")
    report = "\n".join([
        "---QUERY LAYER TEST REPORT---",
        f"Tests run: {len(test_cases)}",
        f"LLM responded: {llm_ok}/{len(test_cases)}",
        f"DB data injected: {db_injected}/{len(test_cases)}",
        f"CRITICAL banner fired: {crit_count} times",
        f"Correct route used: {routes_ok}/{len(test_cases)}",
        f"Issues found: {'; '.join(issues) if issues else 'none'}",
        f"Status: {'READY' if not issues else 'NEEDS FIXES'}",
        "---DONE---",
    ]) + "\n"
    with open(report_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report)
    print(f"\nReport written to {report_path}")
