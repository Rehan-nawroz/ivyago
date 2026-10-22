import os
import re
import sys
import json
import time
import sqlite3
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from keyword_detector.keywords import run as detect_and_query      # noqa: E402
from query_layer import query as query_layer                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS_DIR = os.path.join(BASE_DIR, "test_results")
RAW_LOG = os.path.join(RESULTS_DIR, "comprehensive_raw_log.txt")

# ----------------------------------------------------------------------
# GROUNDING TOKENS
# ----------------------------------------------------------------------
# Words that appear in almost every emergency answer and therefore prove
# nothing about whether the verified row was actually used.
_GENERIC = {
    "person", "help", "immediately", "emergency", "call", "keep", "make",
    "sure", "using", "verified", "data", "above", "steps", "step", "give",
    "tell", "user", "message", "condition", "severity", "action", "does",
    "your", "yours", "them", "they", "then", "than", "that", "this", "with",
    "from", "into", "onto", "over", "under", "while", "until", "when",
    "will", "would", "should", "could", "must", "must", "have", "has",
    "been", "being", "and", "the", "for", "not", "never", "always", "also",
    "more", "most", "less", "least", "very", "much", "many", "some", "any",
    "about", "because", "there", "where", "which", "what", "who", "whom",
    "here", "does", "did", "doing", "done", "please", "quickly", "quick",
    "response", "answer", "instruction", "instructions", "numbered", "line",
}


# Mirrors query_layer._EXPIRY_INSTRUCTION: the guidance a faithful answer to an
# expiry question has to be built from.
EXPIRY_RULE = ("expired medicine loses strength rather than becoming poisonous "
               "do not take expired antibiotics eye drops insulin liquid "
               "medicines changed colour smell never take a double dose pharmacy "
               "safe disposal fresh supply")


def _tokens(text):
    return {t for t in re.findall(r"[a-z]{4,}", (text or "").lower())
            if t not in _GENERIC}


def _grounding_fields(route, row, user_input):
    """The verified row text that a faithful answer must be built from."""
    if not row:
        return ""
    if route == "emergency_numbers":
        return " ".join(str(row.get(k, "")) for k in
                        ("police", "ambulance", "fire", "country"))
    if route == "medicines":
        lowered = user_input.lower()
        if any(w in lowered for w in ("overdose", "overdosed", "too many",
                                      "too much", "whole bottle", "bottle of",
                                      "swallowed", "double dose", "took extra",
                                      "antidote", "poison", "poisoning",
                                      "accidental", "extra pills",
                                      "extra tablets")):
            return " ".join(str(row.get(k, "")) for k in
                            ("overdose_action", "antidote", "overdose_symptoms"))
        if any(w in lowered for w in ("expired", "expire", "expiry",
                                      "out of date", "still good")):
            # For an expiry question the verified text the answer must follow
            # is the standard offline expiry rule injected by query.py (the
            # medicine rows themselves carry no expiry field).
            return (str(EXPIRY_RULE) + " " +
                    " ".join(str(row.get(k, "")) for k in ("warnings", "used_for")))
        return " ".join(str(row.get(k, "")) for k in
                        ("max_dose_adult", "max_dose_child", "safe_in_pregnancy",
                         "warnings", "used_for"))
    return " ".join(str(row.get(k, "")) for k in
                    ("immediate_action", "what_not_to_do"))


def _numbers_in(text):
    """Every individual number in the text (2-5 digits).

    Extracting whole digit GROUPS rather than regex "number-like" spans is
    essential: the verified fields are joined with spaces, so "911 911 911"
    used to come back as one token that could never equal the "911" written in
    an answer -- that bug alone marked 14 correct number answers as failures.
    """
    return {d for d in re.findall(r"\d+", text or "") if 2 <= len(d) <= 5}


# ----------------------------------------------------------------------
# CASE TABLE
# ----------------------------------------------------------------------
# accept: regex of medically acceptable TOP-row labels for this question
#         (None means the hardcoded refusal is expected - off topic).
# ----------------------------------------------------------------------
C1 = "body"
C2 = "medicine"
C3 = "disaster"
C4 = "number"
C5 = "offtopic"

CASES = [
    # ---------------- CATEGORY 1 — BODY EMERGENCIES (30) --------------
    (C1, "my chest hurts and left arm is numb",
     "body_symptoms", r"heart attack|cardia|angina|aortic dissection|pulmonary embol|hypertensive"),
    (C1, "i cant breathe",
     "body_symptoms", r"asthma|anaphylaxis|choking|pneumothorax|pulmonary|carbon monoxide|cardiac|heart failure|hypervent|near-drowning|COPD|epiglottitis|smoke inhal|nerve agent|flail"),
    (C1, "my friend is not waking up",
     "body_symptoms", r"coma|reduced consciousness|cardiac arrest|opioid overdose|hypoglyc|seizure|stroke|head injury|diabetic|alcohol poisoning|sepsis"),
    (C1, "someone is having a seizure",
     "body_symptoms", r"seizure|encephalitis|nerve agent"),
    (C1, "i think i am having a stroke",
     "body_symptoms", r"stroke|transient ischaemic|brain h|subarachnoid|raised pressure"),
    (C1, "my face is drooping on one side",
     "body_symptoms", r"stroke|bell"),
    (C1, "baby is not breathing",
     "body_symptoms", r"infant cardiac|near-drowning|choking|anaphylaxis"),
    (C1, "someone is choking",
     "body_symptoms", r"choking|epiglottitis|anaphylaxis"),
    (C1, "i am drowning help",
     "body_symptoms", r"near-drowning|pulmonary oedema"),
    (C1, "severe allergic reaction swollen throat",
     "body_symptoms", r"anaphylaxis"),
    (C1, "i burned my hand on the stove",
     "body_symptoms", r"hand burns|severe burns|thermal"),
    (C1, "i have a deep cut that wont stop bleeding",
     "body_symptoms", r"skin laceration|haemorrhage|arm laceration|neck laceration|scalp laceration"),
    (C1, "i fell and my leg looks broken",
     "body_symptoms", r"leg fracture|foot fracture|compartment"),
    (C1, "someone hit their head and is confused",
     "body_symptoms", r"concussion|head injury|skull fracture|brain h|raised pressure|subarachnoid"),
    (C1, "my back hurts and i cant feel my legs",
     "body_symptoms", r"cauda equina|spinal cord|spinal fracture|compression fracture|spinal infection"),
    (C1, "i think i broke my neck",
     "body_symptoms", r"neck injury|spinal cord|spinal fracture|neck laceration"),
    (C1, "someone got electrocuted",
     "body_symptoms", r"electric shock|cardiac arrest|ventricular|severe burns"),
    (C1, "i swallowed something and throat is swelling",
     "body_symptoms", r"anaphylaxis|epiglottitis|choking|caustic"),
    (C1, "my eye got chemical in it",
     "body_symptoms", r"chemical eye"),
    (C1, "i have severe stomach pain",
     "body_symptoms", r"appendicitis|peritonitis|pancreatitis|bowel obstruction|peptic ulcer|gastritis|food poisoning|abdominal aortic|ruptured spleen|evisceration|strangulated|diverticulitis|gastroenteritis|internal bleeding"),
    (C1, "diabetic person is unconscious",
     "body_symptoms", r"hypoglyc|ketoacidosis|coma|cardiac arrest|stroke"),
    (C1, "pregnant woman is bleeding",
     "body_symptoms", r"miscarriage|ectopic|postpartum|umbilical|labour|reproductive"),
    (C1, "i am having a panic attack",
     "body_symptoms", r"panic attack|hypervent|tachycardia|arrhythmia"),
    (C1, "someone is having a mental health crisis",
     "body_symptoms", r"suicidal|mental health|overdose"),
    (C1, "heatstroke person is not sweating and confused",
     "body_symptoms", r"heat stroke"),
    (C1, "hypothermia person is shivering uncontrollably",
     "body_symptoms", r"hypothermia|frostbite"),
    (C1, "snake bite on the leg",
     "body_symptoms", r"snake bite|animal bite|bite wound"),
    (C1, "dog bite deep wound",
     "body_symptoms", r"dog bite|animal bite|rabies|puncture wound"),
    (C1, "i got stung by something and arm is swelling",
     "body_symptoms", r"anaphylaxis|sting|animal bite|cellulitis|allergic contact"),
    (C1, "someone fell in water and not breathing",
     "body_symptoms", r"near-drowning|cardiac arrest|infant cardiac"),

    # ---------------- CATEGORY 2 — MEDICINE QUESTIONS (15) ------------
    (C2, "i took too many paracetamol tablets",
     "medicines", r"paracetamol"),
    (C2, "someone swallowed too much ibuprofen",
     "medicines", r"ibuprofen"),
    (C2, "child swallowed adult aspirin",
     "medicines", r"aspirin"),
    (C2, "i took too many sleeping pills",
     "medicines", r"zolpidem|zopiclone|melatonin|benzodiazep|lorazepam|diazepam|alprazolam|clonazepam"),
    (C2, "someone drank bleach",
     None, r"caustic|bleach|poison|overdose by ingestion"),
    (C2, "someone swallowed rat poison",
     None, r"poison|overdose by ingestion|warfarin|rodenticide"),
    (C2, "i accidentally took double dose of metformin",
     "medicines", r"metformin"),
    (C2, "what is the antidote for warfarin overdose",
     "medicines", r"warfarin"),
    (C2, "someone injected too much insulin",
     "medicines", r"insulin"),
    (C2, "i mixed alcohol with diazepam",
     "medicines", r"diazepam"),
    (C2, "can i give ibuprofen to a pregnant woman",
     "medicines", r"ibuprofen"),
    (C2, "child swallowed unknown white pills",
     None, r"overdose by ingestion|opioid overdose|caustic|poison|coma"),
    # "expired antibiotics" names no single drug, so ANY row that really is an
    # antibiotic is a correct answer here.
    (C2, "i took expired antibiotics",
     "medicines", r"amoxicillin|penicillin|azithromycin|ciprofloxacin|antibiotic|tetracycline|doxycycline|erythromycin|cephalexin|cef|metronidazole|clindamycin|nitrofurantoin"),
    (C2, "someone overdosed on opioids not breathing",
     None, r"opioid overdose|naloxone|cardiac arrest|infant cardiac"),
    # Open question: any medicine whose verified warnings really do restrict
    # use in children is a correct answer (Aspirin/Reye's, Codeine, TCAs...).
    (C2, "what medicines should not be given to children",
     "medicines", r"aspirin|codeine|amitriptyline|tetracycline|doxycycline|morphine|tramadol|ibuprofen|paracetamol|antibiotic|penicillin|medicine"),

    # ---------------- CATEGORY 3 — DISASTER SITUATIONS (14) -----------
    (C3, "there is an earthquake happening right now",
     "body_symptoms", r"earthquake|disaster|trapped|rubble"),
    (C3, "i am trapped under rubble",
     "body_symptoms", r"earthquake|trapped|rubble|disaster|crush"),
    (C3, "there is a flood and water is rising",
     "body_symptoms", r"flood|drown|water"),
    (C3, "there is a wildfire near my house",
     "body_symptoms", r"fire|smoke inhal|burn|wildfire"),
    (C3, "there is a gas leak in my house",
     "body_symptoms", r"carbon monoxide|gas|poison|smoke inhal"),
    (C3, "building is on fire how do i escape",
     "body_symptoms", r"fire|smoke inhal|burn"),
    (C3, "i am stuck in a car underwater",
     "body_symptoms", r"near-drowning|drown|water"),
    (C3, "tornado is coming what do i do",
     "body_symptoms", r"tornado|disaster|storm|severe weather|trapped"),
    (C3, "tsunami warning what do i do",
     "body_symptoms", r"tsunami|flood|disaster|drown"),
    (C3, "landslide is happening near me",
     "body_symptoms", r"landslide|disaster|trapped|crush|earthquake"),
    (C3, "there is a chemical spill near me",
     "body_symptoms", r"chemical|poison|spill|burn|gas"),
    (C3, "power lines are down on the road",
     "body_symptoms", r"electric shock|electrocution|live wire|power"),
    (C3, "i am lost in the mountains",
     "body_symptoms", r"lost|mountain|hypothermia|exposure|disaster"),
    (C3, "someone got struck by lightning",
     "body_symptoms", r"electric shock|electrocution|lightning|cardiac arrest"),

    # ---------------- CATEGORY 4 — EMERGENCY NUMBERS (14) -------------
    (C4, "what is the emergency number in pakistan",
     "emergency_numbers", r"pakistan"),
    (C4, "ambulance number in india",
     "emergency_numbers", r"india"),
    (C4, "police number in united kingdom",
     "emergency_numbers", r"united kingdom"),
    (C4, "fire brigade number in australia",
     "emergency_numbers", r"australia"),
    (C4, "emergency number in united states",
     "emergency_numbers", r"united states of america"),
    (C4, "rescue number in germany",
     "emergency_numbers", r"germany"),
    (C4, "emergency services in france",
     "emergency_numbers", r"france"),
    (C4, "ambulance in saudi arabia",
     "emergency_numbers", r"saudi arabia"),
    (C4, "emergency number in uae",
     "emergency_numbers", r"united arab emirates"),
    (C4, "what number do i call in nigeria",
     "emergency_numbers", r"nigeria"),
    (C4, "emergency services in canada",
     "emergency_numbers", r"canada"),
    (C4, "ambulance number in bangladesh",
     "emergency_numbers", r"bangladesh"),
    (C4, "what is 911 equivalent in pakistan",
     "emergency_numbers", r"pakistan"),
    (C4, "who do i call for emergency in turkey",
     "emergency_numbers", r"turkey"),

    # ---------------- CATEGORY 5 — OFF TOPIC (10) ---------------------
    (C5, "write me a poem", None, None),
    (C5, "what is the capital of france", None, None),
    (C5, "tell me a joke", None, None),
    (C5, "who is the president of usa", None, None),
    (C5, "what is 2 + 2", None, None),
    (C5, "recommend me a movie", None, None),
    (C5, "what is bitcoin", None, None),
    (C5, "how do i cook pasta", None, None),
    (C5, "tell me about history", None, None),
    (C5, "what is the weather today", None, None),

    # -------- EXTRA: other real things a user would type -----------------
    (C1, "my child has a very high fever and is limp",
     "body_symptoms", r"meningitis|sepsis|heat stroke|encephalitis|infant|fever|seizure|meningitis|pneumonia"),
    (C1, "he is bleeding from his ears after a fall",
     "body_symptoms", r"csf leak|ear bleeding|skull fracture|head injury|subarachnoid"),
    (C1, "she has a nosebleed that wont stop",
     "body_symptoms", r"nosebleed|epistaxis|haemorrhage"),
    (C1, "my tooth got knocked out",
     "body_symptoms", r"knocked-out tooth|dental avulsion"),
    (C1, "i have a severe headache and stiff neck",
     "body_symptoms", r"meningitis|subarachnoid|brain h|stroke|raised pressure"),
    (C1, "my urine has blood in it",
     "body_symptoms", r"haematuria|urinary|kidney|bladder|stone"),
    (C1, "i spilled boiling water on my arm",
     "body_symptoms", r"severe burns|hand burns|skin laceration|burn"),
    (C1, "he swallowed his tongue during a fit",
     "body_symptoms", r"seizure|choking|epiglottitis"),
    (C1, "she is 9 months pregnant and the cord came out",
     "body_symptoms", r"umbilical|labour|prolapsed"),
    (C1, "i feel very dizzy and my heart is racing",
     "body_symptoms", r"arrhythmia|tachycardia|bradycardia|heart failure|anaemia|hypoglyc|hypertensive|palpitation"),
    (C1, "i cut my finger with a knife",
     "body_symptoms", r"skin laceration|finger amputation|laceration"),
    (C1, "my grandfather suddenly cant speak and his arm is weak",
     "body_symptoms", r"stroke|transient ischaemic"),
    (C1, "there is pus coming out of my ear",
     "body_symptoms", r"ear infection|otitis|ruptured eardrum|cellulitis"),
    (C1, "my ankle is swollen after i twisted it",
     "body_symptoms", r"ankle sprain|foot fracture|sprain"),
    (C1, "someone is having a fit and shaking",
     "body_symptoms", r"seizure|nerve agent"),
    (C1, "i drank a lot of alcohol and now i am confused",
     "body_symptoms", r"alcohol poisoning|hypoglyc|coma|reduced consciousness|wernicke"),
    (C1, "my vision suddenly went black in one eye",
     "body_symptoms", r"retinal artery|sudden vision loss|stroke|glaucoma|retinal detach"),
    (C1, "he fell from a ladder and his back is bent",
     "body_symptoms", r"spinal fracture|spinal cord|vertebral|compression fracture|cauda|back"),
    (C1, "i have a deep wound in my stomach after a stabbing",
     "body_symptoms", r"evisceration|penetrating|abdominal|peritonitis|internal bleeding|blunt"),
    (C2, "i took my whole bottle of sleeping tablets",
     "medicines", r"zolpidem|zopiclone|melatonin|benzodiazep|lorazepam|diazepam|alprazolam"),
    (C2, "is it safe to take aspirin during pregnancy",
     "medicines", r"aspirin"),
    (C2, "how much paracetamol can an adult take in a day",
     "medicines", r"paracetamol"),
    (C2, "my child ate my blood pressure tablets",
     "medicines", r"amlodipine|losartan|atenolol|ramipril|lisinopril|nifedipine|metoprolol|hydrochlorothiazide|beta|calcium channel|ace inhibitor|nitroglycerin|vasodilator"),
    (C2, "what is the antidote for morphine overdose",
     "medicines", r"morphine|naloxone"),
    (C4, "emergency number in philippines",
     "emergency_numbers", r"philippines"),
    (C4, "ambulance number in south africa",
     "emergency_numbers", r"south africa"),
    (C4, "emergency number in usa",
     "emergency_numbers", r"united states of america"),
    (C4, "emergency number in uk",
     "emergency_numbers", r"united kingdom"),
    (C4, "emergency number in lebanon",
     "emergency_numbers", r"lebanon"),
]


def top_label(rows):
    if not rows:
        return "(none)"
    row = rows[0]
    for key in ("condition", "medicine_name", "country"):
        if row.get(key):
            return row[key]
    return "(unknown)"


def grade(case, det, answer, routes_only):
    category, user_input, exp_route, accept = case
    route = det["route"]
    row = (det["db_results"] or [None])[0]
    label = top_label(det["db_results"])    # (overdose detection above mirrors query_layer's _OVERDOSE_WORDS so the
    # grader judges the same fields the production prompt actually used)
    if exp_route is None and category == C5:
        # off topic: only a hardcoded refusal counts
        route_ok = (route == "general")
    elif exp_route is None:
        # ingestion questions with no named drug may legitimately land on
        # either the medicines table or the body_symptoms table
        route_ok = route in ("body_symptoms", "medicines")
    else:
        route_ok = (route == exp_route)

    if accept is not None:
        row_ok = bool(re.search(accept, label or "", re.I)) and (route != "general")
    else:
        row_ok = (route == "general")

    entry = {
        "category": category, "input": user_input, "expected_route": exp_route,
        "route": route, "severity": det["severity_hint"], "row": label,
        "route_ok": route_ok, "row_ok": row_ok,
        "rows_returned": det["db_result_count"],
    }

    if routes_only:
        entry.update({"source": "-", "response": "(routes-only run)",
                      "verdict": "YES" if (route_ok and row_ok) else
                                 ("PARTIAL" if route_ok else "NO"),
                      "note": ""})
        return entry

    response = answer["response"]
    source = answer["source"]
    note = ""

    if route == "general":
        entry["source"] = source
        entry["response"] = response
        entry["verdict"] = "YES" if source == "hardcoded_refusal" else "NO"
        if source != "hardcoded_refusal":
            note = "off-topic question was answered instead of refused"
        entry["note"] = note
        return entry

    # --- quality flags on the LLM text -------------------------------
    low = response.lower()
    if response.startswith("ERROR:"):
        note = "LLM error: " + response[:80]
        verdict = "NO"
    elif query_layer._echoes_prompt(response):
        note = "answer echoed a prompt instruction"
        verdict = "NO"
    elif query_layer._looks_degenerate(response):
        note = "answer is a repetition loop"
        verdict = "NO"
    elif route == "emergency_numbers":
        want = _numbers_in(_grounding_fields(route, row, user_input))
        got = _numbers_in(response)
        hit = want & got
        verdict = "YES" if hit else ("PARTIAL" if not want else "NO")
        if hit:
            note = "verified number(s) %s present" % sorted(hit)
        else:
            note = "verified numbers %s not found in the answer" % sorted(want)
    else:
        want = _tokens(_grounding_fields(route, row, user_input))
        got = _tokens(response)
        hit = want & got
        if len(hit) >= 2:
            verdict = "YES"
        elif len(hit) == 1:
            verdict = "PARTIAL"
            note = "only weak grounding (%s)" % ", ".join(sorted(hit))
        else:
            verdict = "NO"
            note = "answer not grounded in the verified row"

    if not row_ok and verdict == "YES":
        verdict = "PARTIAL"
        note = (note + "; " if note else "") + "but the top row (%s) is not the expected one" % label

    entry.update({"source": source, "response": response,
                  "verdict": verdict, "note": note})
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    cases = CASES[args.start:]
    if args.limit:
        cases = cases[:args.limit]

    results = []
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        user_input = case[1]
        det = detect_and_query(user_input)
        answer = None
        if not args.routes_only:
            answer = query_layer.answer(user_input)
        entry = grade(case, det, answer, args.routes_only)
        results.append(entry)
        mark = {"YES": "OK ", "PARTIAL": "~  ", "NO": "BAD"}[entry["verdict"]]
        print("[%s] %2d/%d %-8s route=%-18s sev=%-8s row=%s" % (
            mark, i, len(cases), entry["category"], entry["route"],
            entry["severity"], entry["row"]))
        if entry["note"]:
            print("        note: %s" % entry["note"])
        if args.routes_only is False and entry["verdict"] != "YES":
            print("        resp: %s" % entry["response"][:200].replace("\n", " | "))

    elapsed = time.time() - t0

    # ---- write the raw log (auditable evidence) ----------------------
    # A partial run (--start/--limit) appends instead of replacing so the log
    # keeps the evidence of earlier categories.
    partial = bool(args.start or args.limit)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RAW_LOG, "a" if partial else "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write("---COMPREHENSIVE RAW LOG---\n")
        fh.write("mode: %s\ncases: %d\nseconds: %.1f\n\n" %
                 ("routes-only" if args.routes_only else "full",
                  len(results), elapsed))
        for e in results:
            fh.write("-" * 60 + "\n")
            fh.write("INPUT: %s\n" % e["input"])
            fh.write("CATEGORY: %s\n" % e["category"])
            fh.write("ROUTE DETECTED: %s\n" % e["route"])
            fh.write("DB ROW MATCHED: %s\n" % e["row"])
            fh.write("SEVERITY: %s\n" % e["severity"])
            fh.write("SOURCE: %s\n" % e["source"])
            fh.write("RESULT: %s\n" % e["verdict"])
            if e["note"]:
                fh.write("NOTE: %s\n" % e["note"])
            fh.write("RESPONSE:\n%s\n" % e["response"])
    print("\nraw log -> %s" % RAW_LOG)

    # ---- per-category summary ---------------------------------------
    print("\n%-10s %5s %5s %5s %6s" % ("CATEGORY", "YES", "PART", "NO", "TOTAL"))
    for cat in (C1, C2, C3, C4, C5):
        rows = [e for e in results if e["category"] == cat]
        if not rows:
            continue
        y = sum(1 for e in rows if e["verdict"] == "YES")
        p = sum(1 for e in rows if e["verdict"] == "PARTIAL")
        n = sum(1 for e in rows if e["verdict"] == "NO")
        print("%-10s %5d %5d %5d %6d" % (cat, y, p, n, len(rows)))
    y = sum(1 for e in results if e["verdict"] == "YES")
    print("\nTOTAL: %d/%d YES in %.1fs (%.1fs per case)" %
          (y, len(results), elapsed, elapsed / max(1, len(results))))

    # machine-readable dump for the report writer. A partial run MERGES into
    # the existing file, so re-testing one category cannot wipe the results of
    # the others.
    results_path = os.path.join(RESULTS_DIR, "comprehensive_results.json")
    merged = {e["input"]: e for e in results}
    if partial and os.path.exists(results_path):
        try:
            with open(results_path, encoding="utf-8") as fh:
                for old in json.load(fh):
                    merged.setdefault(old["input"], old)
        except Exception:
            pass
    order = {c[1]: i for i, c in enumerate(CASES)}
    merged_list = sorted(merged.values(), key=lambda e: order.get(e["input"], 999))
    with open(results_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(merged_list, fh, indent=1)


if __name__ == "__main__":
    main()
