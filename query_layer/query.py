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
    * temperature stays at 0.1 so the LLM stays conservative with
      safety-critical facts -- local DB rows are optional reference material,
      not a forced answer for every question.
    * the LLM is NEVER called without a system prompt.
    * Relevant DB data is injected as optional context when the detector finds
      a likely match. The model must still answer the user's actual question
      and must not force an unrelated row into the response.
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

# The pure prompt/output-safety policy is shared with the offline desktop
# assistant, which must reuse these exact rules WITHOUT importing this module
# (this module pulls in `requests` and drives Ollama via call_llm). The rules
# therefore live in a stdlib-only module and are re-imported here so every
# public and private name below is unchanged for the CLI and its tests.
try:  # pragma: no cover - the fallback only matters when run as a script
    from query_layer.prompt_policy import (
        _EMPTY_REPLY,
        _ECHO_SAFE_REPLY,
        _EXPIRY_INSTRUCTION,
        _EXPIRY_WORDS,
        _OVERDOSE_WORDS,
        _POSITIVE_SAFETY_CLAIMS,
        _PREGNANCY_MARKERS,
        _PROMPT_ECHO_MARKERS,
        _SAFETY_DENIALS,
        _SAFETY_WORDS,
        _echoes_prompt,
        _inverts_safety_verdict,
        _is_expiry_question,
        _is_overdose_question,
        _is_safety_question,
        _looks_degenerate,
        _pregnancy_text,
        build_db_fallback,
        build_system_prompt,
        build_user_prompt,
        clean_response,
    )
except ImportError:  # pragma: no cover - direct-script fallback
    from prompt_policy import (  # noqa: F401
        _EMPTY_REPLY,
        _ECHO_SAFE_REPLY,
        _EXPIRY_INSTRUCTION,
        _EXPIRY_WORDS,
        _OVERDOSE_WORDS,
        _POSITIVE_SAFETY_CLAIMS,
        _PREGNANCY_MARKERS,
        _PROMPT_ECHO_MARKERS,
        _SAFETY_DENIALS,
        _SAFETY_WORDS,
        _echoes_prompt,
        _inverts_safety_verdict,
        _is_expiry_question,
        _is_overdose_question,
        _is_safety_question,
        _looks_degenerate,
        _pregnancy_text,
        build_db_fallback,
        build_system_prompt,
        build_user_prompt,
        clean_response,
    )

# ----------------------------------------------------------------------
# Ollama configuration
# ----------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:0.5b"
OLLAMA_TIMEOUT = 30  # seconds before giving up on the LLM


# [build_system_prompt, build_user_prompt, and their pure helpers moved to
#  query_layer/prompt_policy.py and are re-imported above.]



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


# [clean_response and its _EMPTY_REPLY sentinel moved to query_layer/prompt_policy.py]


def build_banner(severity: str) -> str:
    if severity == "CRITICAL":
        return "🔴 CRITICAL EMERGENCY — FOLLOW STEPS IMMEDIATELY"
    if severity == "URGENT":
        return "🟡 URGENT — NEEDS ATTENTION SOON"
    if severity == "MODERATE":
        return "🟢 MODERATE — MANAGEABLE SITUATION"
    return "ℹ️  GENERAL ASSISTANCE"


# [The output-safety guards (_echoes_prompt, _looks_degenerate,
#  _inverts_safety_verdict) and build_db_fallback moved to
#  query_layer/prompt_policy.py and are re-imported above.]


def answer(user_input: str) -> dict:
    # Step 1 -- detect route + severity and fetch verified DB rows.
    detection = detect_and_query(user_input)
    route = detection.get("route", "general")
    severity_hint = detection.get("severity_hint", "UNKNOWN")
    critical_override = detection.get("critical_override", False)
    db_results = detection.get("db_results", [])
    db_result_count = detection.get("db_result_count", 0)

    # A general question still goes to the offline model. The detector only
    # decides whether optional local reference context is available; it is not
    # a gate that can refuse or reroute an unexpected question.

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
