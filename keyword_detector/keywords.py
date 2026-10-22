"""
keyword_detector/keywords.py
============================
The "brain" that runs BEFORE the LLM. It reads the user's raw message,
decides which database is relevant, guesses how urgent it is, and pulls
the best-matching rows from SQLite so the LLM only has to format the answer.

Standalone usage:  python keywords.py
Import usage:      from keywords import run;  result = run("my chest hurts")

Only the Python standard library + sqlite3 are used. All DB paths are
resolved relative to THIS file, so it works on any machine / any clone.
"""

import os
import re
import sys
import sqlite3

# Make console output safe on Windows (cp1252) terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --- Things that map to body_symptoms.db ---------------------------------
BODY_SYMPTOM_KEYWORDS = [
    # chest / heart
    "chest pain", "chest hurts", "chest hurt", "chest tight", "chest tightness",
    "chest pressure", "chest squeezing", "crushing chest", "pain in chest",
    "heart attack", "heart hurts", "left arm pain", "left arm hurts", "arm hurts",
    "jaw pain", "palpitations", "racing heart", "fast heartbeat",

    # breathing
    "cant breathe", "can't breathe", "cannot breathe", "hard to breathe",
    "trouble breathing", "difficulty breathing", "breathing problems",
    "short of breath", "shortness of breath", "breathless", "wheezing",
    "gasping", "suffocating", "struggling to breathe", "not breathing",
    "stopped breathing", "no breath", "cant catch breath", "coughing blood",

    # bleeding / wounds
    "bleeding", "severe bleeding", "heavy bleeding", "bleeding a lot",
    "wont stop bleeding", "won't stop bleeding", "bleeding won't stop",
    "blood loss", "blood everywhere", "hemorrhage", "haemorrhage",
    "deep cut", "cut", "gash", "laceration", "stab wound", "gunshot",

    # burns
    "burn", "burned", "burnt", "scald", "scalded", "chemical burn",
    "burning skin", "electrical burn", "burn on hand", "burned my hand",

    # broken bones / fractures
    "broken bone", "broken arm", "broken leg", "broken wrist", "broken ankle",
    "broken rib", "fracture", "dislocated", "bone sticking out", "bent arm",
    "swollen arm injury",

    # head injuries
    "head injury", "hit my head", "head trauma", "concussion", "skull",
    "skull fracture", "head wound", "bleeding from head", "dent in head",

    # stroke
    "stroke", "face drooping", "drooping face", "slurred speech", "cant speak",
    "cant talk", "weakness on one side", "numb arm", "numb face", "numbness",
    "sudden weakness", "vision loss", "blurred vision", "thunderclap headache",
    "worst headache ever", "sudden severe headache",

    # seizures
    "seizure", "seizures", "convulsion", "convulsions", "convulsing", "fitting",
    "fits", "shaking uncontrollably", "epileptic",

    # allergic reactions
    "allergic reaction", "allergy", "anaphylaxis", "hives", "swollen throat",
    "throat closing", "swollen tongue", "swollen face", "swollen lips",
    "bee sting", "wasp sting", "insect sting",

    # choking / airway
    "choking", "choked", "something stuck in throat", "food stuck",
    "cant swallow", "airway blocked", "blue lips", "turning blue",

    # drowning
    "drowning", "drowned", "near drowning", "underwater", "inhaled water",
    "water in lungs",

    # poisoning / overdose by ingestion
    "poison", "poisoning", "poisoned", "swallowed bleach", "swallowed chemicals",
    "drank chemicals", "swallowed pills", "swallowed tablets", "took poison",
    "pesticide", "toxic", "overdosed on pills", "overdose", "overdosed",
    "took too many pills", "too many pills", "too many tablets",
    "whole bottle of pills", "whole bottle of tablets", "drug overdose",
    "alcohol poisoning", "drank too much", "drunk and unresponsive",
    "passed out drunk", "opioid", "heroin", "fentanyl", "opioid overdose",

    # eye injuries
    "eye injury", "something in my eye", "chemical in eye", "bleach in eye",
    "eye pain", "eye burning", "burnt eye", "eye splash", "sudden vision loss",

    # back / spine
    "back injury", "back pain", "spinal", "spine", "neck injury", "broken back",
    "cant move my legs", "cant feel my legs", "numb legs", "spinal cord",

    # pregnancy / birth
    "pregnant", "pregnancy", "bleeding pregnant", "miscarriage", "contractions",
    "labour", "labor", "water broke", "baby coming", "giving birth", "ectopic",
    "cord prolapse",

    # diabetic emergencies
    "diabetic", "low blood sugar", "high blood sugar", "hypoglycemia",
    "hypoglycaemia", "hyperglycemia", "hyperglycaemia", "sugar low", "sugar high",
    "low sugar", "high sugar", "very low sugar", "very high sugar",
    "insulin shock", "insulin reaction", "diabetic coma", "diabetic emergency",
    "ketoacidosis", "dka", "fruity breath", "acetone breath",

    # mental health crisis
    "suicidal", "suicidal thoughts", "suicide", "want to die", "kill myself",
    "self harm", "self-harm", "self harming", "feeling hopeless",
    "mental health crisis", "overdose on tablets", "panic attack",
    "severe anxiety", "depressed",

    # animal bites / stings / envenomation
    "animal bite", "dog bite", "snake bite", "snakebite", "snake", "bitten",
    "bitten by a snake", "cat bite", "scorpion sting", "spider bite",
    "venom", "venomous", "rabies", "bite wound",

    # electric shock
    "electric shock", "electrocuted", "electrocution", "electrical shock",
    "live wire", "lightning strike", "shocked by electricity",

    # temperature extremes
    "hypothermia", "frostbite", "freezing", "too cold", "very cold", "frozen",
    "low body temperature", "stopped shivering", "exposure to cold",
    "cold and confused", "heat stroke", "heatstroke", "heat exhaustion",
    "sunstroke", "too hot", "overheating", "heat collapse",

    # gas / carbon monoxide
    "carbon monoxide", "co poisoning", "gas leak", "gas poisoning",
    "exhaust fumes", "faulty heater", "heater fumes", "smoke inhalation",

    # infant / child
    "baby", "infant", "newborn", "baby not breathing", "baby is not breathing",
    "baby wont wake", "baby unresponsive", "baby limp", "baby choking",
    "baby fever", "baby fell", "child not breathing", "toddler",

    # neuro / general severe
    "unconscious", "unresponsive", "fainted", "passed out", "coma",
    "wont wake up", "won't wake up", "not waking up", "dizzy", "dizziness",
    "headache", "severe headache", "stiff neck", "paralysis",
    "severe pain", "vomiting blood", "blood in vomit", "throwing up blood",
    "severe stomach pain", "sudden collapse", "cant move",

    # --- everyday words for the same emergencies (recall fixes) ---------
    # These cover presentations that real people type constantly but the
    # clinical list above never named: fever, vomiting, swelling, toothache,
    # a scalded arm, a stabbing, confusion, a nosebleed, a fall. Route
    # tolerance is handled by the matcher, vocabulary has to exist first.
    "fever", "high fever", "very high fever",
    "vomiting", "throwing up", "cant stop vomiting", "nausea", "diarrhea",
    "diarrhoea", "loose motions", "stomach hurts", "stomach ache",
    "stomach pain", "abdominal pain", "belly pain",
    "rash", "rash all over", "spots on skin", "itchy rash",
    "swollen", "swelling", "swollen leg", "swollen foot", "swollen joint",
    "swollen hand", "red and swollen", "red and hot", "spreading redness",
    "toothache", "tooth hurts", "tooth pain", "dental pain",
    "earache", "ear hurts", "ear pain", "ear infection", "pus from ear",
    "urinary infection", "uti", "blood in urine", "blood in my urine",
    "burning when i pee", "painful urination",
    "back hurts", "back ache", "head hurts", "head pain", "sore throat",
    "weakness", "very weak", "fatigue", "very tired", "faint", "fainting",
    "dizzy spell", "lightheaded", "light headed",
    "stabbed", "stabbing", "penetrating wound", "impaled", "deep stab",
    "severed", "severed finger", "severed arm", "amputated", "amputation",
    "cut off", "sliced off", "torn off", "chopped off", "lost a finger",
    "finger is gone", "finger came off", "body part is missing",
    "nosebleed", "nose bleed", "nose bleeding", "bleeding nose",
    "fell", "fell down", "fall from height", "fall down stairs",
    "boiling water", "hot water", "hot liquid", "spilled hot", "hot oil",
    "steam burn", "acid", "acid burn", "chemical splash",
    "shaking", "shivering", "sweating", "cold sweat",
    "confused", "confusion", "slurring", "not making sense", "disoriented",
    "fish bone", "bone stuck", "difficulty swallowing",

    # --- ear / discharge (recall fix) ---------------------------------
    "pus", "pus from my ear", "pus from ear", "pus in ear", "ear discharge",
    "discharge from my ear", "discharge from ear", "fluid from my ear",
    "ear is leaking", "leaking from my ear",

    # --- seizure wording (recall fix) ---------------------------------
    "fit", "having a fit", "during a fit", "epileptic fit", "swallowed tongue",
    "swallowed his tongue", "swallowed her tongue", "swallowed my tongue",
    "biting his tongue", "biting her tongue", "foaming at the mouth",

    # --- pregnancy / birth (recall fix) -------------------------------
    "cord came out", "cord is out", "cord hanging out", "umbilical cord",
    "months pregnant", "in labour", "giving birth", "baby is coming",

    # --- alcohol (recall fix) -----------------------------------------
    "alcohol", "drank alcohol", "drank a lot", "lots of alcohol",
    "drinking alcohol", "alcohol poisoning",

    # --- back / fall from height (recall fix) -------------------------
    "bent back", "back is bent", "back injury", "hurt my back", "broke my back",
    "fell from a ladder", "fell off a ladder", "fell from height", "fall from height",

    # --- ankle / joint (recall fix) -----------------------------------
    "twisted my ankle", "twisted ankle", "sprained my ankle", "ankle is swollen",
    "swollen ankle", "swollen joint",

    # --- neck / spine (recall fix) ------------------------------------
    # "i think i broke my neck" used to fall all the way through to the
    # general route: the DB has a Neck injury row, the vocabulary did not.
    "broke my neck", "broken neck", "neck is broken", "snapped my neck",
    "hurt my neck", "my neck hurts", "neck pain", "neck injury", "broke my back",

    # --- eye / vision (recall fix) ------------------------------------
    "vision loss", "lost my vision", "lost vision", "went blind", "gone blind",
    "vision went black", "cant see", "cannot see", "sudden blindness",
    "lost sight",

    # --- dental (recall fix) ------------------------------------------
    "knocked out tooth", "tooth knocked out", "tooth got knocked out",
    "tooth is out", "tooth came out", "tooth fell out", "lost my tooth",
    "knocked my tooth", "broken tooth", "cracked tooth",

    # --- ingestion of household poisons (recall fix) -------------------
    "bleach", "drank bleach", "drink bleach", "swallowed bleach",
    "drain cleaner", "caustic", "rat poison", "rodenticide", "mouse poison",
    "weed killer", "kerosene", "petrol", "paraffin", "button battery",
    "swallowed a battery",

    # --- burns (recall fix) -------------------------------------------
    "boiling water", "scald", "scalded", "steam burn", "hot oil",
    "burned my arm", "burned my hand", "burnt my hand", "burning my hand",
    "burn on hand", "spilled hot", "hot water", "spilled boiling",

    # --- knife / cutting injuries --------------------------------------
    "cut my finger", "cut my hand", "cut myself", "cut my arm", "knife",
    "sliced my", "sliced open",

    # --- disasters (route fix) ----------------------------------------
    # None of these reached any database before: an earthquake, a flood, a
    # wildfire and a tsunami were all answered with the hardcoded refusal
    # because the vocabulary did not know the words existed.
    "earthquake", "earth quake", "tremor", "aftershock", "flood", "flooding",
    "flash flood", "rising water", "wildfire", "wild fire", "forest fire",
    "bushfire", "building is on fire", "house is on fire", "on fire",
    "fire escape", "escape a fire", "tornado", "twister", "cyclone",
    "hurricane", "typhoon", "tsunami", "tidal wave", "landslide",
    "land slide", "mudslide", "avalanche", "chemical spill", "toxic spill",
    "hazmat", "power lines", "power line", "downed power lines", "live wire",
    "struck by lightning", "lightning strike", "lightning", "rubble",
    "trapped under", "stuck under rubble", "crush injury", "lost in the jungle",
    "lost in the forest", "lost in the mountains", "lost in the woods",
    "stranded", "survival", "shelter", "evacuate", "evacuation",

    # --- deliberate injury / everyday trauma wording (live user testing) ---
    # Found in live testing: "my arm is badly injured by a bullet" and "i got
    # shot in the leg" matched no keyword at all, so the route stayed
    # "general" and the user got the off-topic refusal even once the Gunshot
    # Wound row existed in the database. The same gap covered crush injuries
    # and the everyday names for heartburn.
    "bullet", "bullet wound", "bullet in", "gunshot", "gun shot",
    "gun wound", "gun injury", "gun", "shot", "shot in", "shot by",
    "firearm", "fired at", "got shot", "been shot", "someone was shot",
    "stab wound", "knife wound", "knifed", "stabbed in", "got stabbed",
    "acid attack", "acid thrown", "acid in my eye", "acid on my",
    "corrosive", "chemical burn",
    "crushed", "crushed by", "crushed my", "crush my", "crush injury",
    "trapped under car", "trapped under a car", "car on my leg",
    "heavy object on", "pinned", "pinned under", "smashed",
    "drowning", "drowned", "drowned in", "near drowning", "cant swim",
    "swallowed water", "under water", "underwater",
    "electrocuted", "electrocution", "electrified", "lightning strike",
    "heartburn", "acid reflux", "indigestion",
    "injured", "badly injured", "severe bleeding", "heavy bleeding",
    # A finger crushed in a door is a nail injury, not the CRITICAL
    # "crush injury trapped under rubble" row, which it used to be answered
    # with because the message only shared the single word "crushed".
    "crushed my finger", "crushed finger", "smashed my finger", "smashed finger",
    "finger in the door", "finger caught in", "finger caught in the door",
    "slammed my finger", "slammed finger", "fingertip", "fingertip injury",
    "hand caught in", "nail injury", "under my nail", "blood under my nail",
]

# --- Drug / brand names (also used to tell a *named* drug apart from a
#     generic overdose message in detect()) -------------------------------
DRUG_NAME_KEYWORDS = [
    "paracetamol", "acetaminophen", "tylenol", "panadol", "calpol",
    "ibuprofen", "advil", "motrin", "naproxen", "diclofenac", "aspirin",
    "morphine", "codeine", "oxycodone", "tramadol", "fentanyl",
    "diazepam", "valium", "xanax", "alprazolam", "lorazepam",
    "amoxicillin", "penicillin", "azithromycin", "ciprofloxacin", "antibiotics",
    "insulin", "metformin", "glibenclamide",
    "warfarin", "heparin", "clopidogrel",
    "amlodipine", "losartan", "atenolol", "ramipril", "lisinopril",
    "simvastatin", "atorvastatin", "rosuvastatin",
    "levothyroxine", "thyroxine", "prednisone", "prednisolone",
    "salbutamol", "albuterol", "ventolin", "budesonide",
    "cetirizine", "loratadine", "benadryl", "diphenhydramine",
    "omeprazole", "ranitidine", "pantoprazole",
    "sertraline", "fluoxetine", "prozac", "zoloft", "amitriptyline",
    "phenytoin", "carbamazepine", "valproate", "lithium",
    "digoxin", "theophylline", "methotrexate",
    "sildenafil", "viagra", "tadalafil",
    # Not a brand name, but a real way people name the drug they took -- the
    # overdose reroute below must keep these on the medicines route so the
    # right overdose_action / antidote is injected instead of a generic
    # "swallowed pills" row.
    "sleeping pills", "sleeping tablets", "sleeping pill", "sleeping tablet",
]

# --- Things that map to medicines.db -------------------------------------
MEDICINE_KEYWORDS = [
    # overdose / ingestion
    "overdose", "overdosed", "took too many", "too many pills",
    "too many tablets", "too many of my", "swallowed", "swallowed tablets",
    "took extra", "double dose", "accidental overdose", "took too much",
    "extra pills", "whole bottle of",

    # generic medicine words
    "medicine", "medication", "tablet", "tablets", "pill", "pills", "capsule",
    "drug", "drugs", "antibiotic", "painkiller", "syrup", "injection",
    "antidote", "dose", "dosage", "mg", "milligrams",

    # dose / usage questions
    "how much should i take", "how many tablets", "how many pills",
    "safe dose", "max dose", "double up", "missed dose", "skip dose",

    # medicine reactions
    "side effect", "side effects", "reaction to medicine", "allergic to medicine",
    "allergic to penicillin", "rash after medicine", "mixed medications",
    "mixed medicines", "medicine interaction", "drug interaction",
    "took with alcohol", "with alcohol", "interaction",

    # expired / storage
    "expired medicine", "expired", "out of date medicine", "is it still good",

    # common drug / brand names live in DRUG_NAME_KEYWORDS above, which also
    # lets detect() distinguish a *named* drug from a generic overdose message.
] + DRUG_NAME_KEYWORDS

# --- Things that map to emergency_numbers.db -----------------------------
EMERGENCY_NUMBER_KEYWORDS = [
    "emergency number", "emergency numbers", "emergency services",
    "emergency line", "emergency contact", "number to call",
    "what number", "which number", "what is the number", "who do i call",
    "who to call", "who should i call", "call for help", "call an ambulance",
    "ambulance", "ambulance number", "police", "police number",
    "fire brigade", "fire department", "fire number", "fire",
    "helpline", "hotline", "rescue", "coast guard", "mountain rescue",
    "contact", "dial", "emergency", "911", "112", "999", "108",
    "emergency in", "number in",
]


# --- CRITICAL overrides: ALWAYS return severity CRITICAL ----------------
# These are unambiguous, time-critical presentations. If any appear we
# short-circuit and mark the detection as a critical override.
CRITICAL_OVERRIDE_KEYWORDS = [
    "not breathing", "no pulse", "unconscious", "not waking up",
    "wont wake up", "won't wake up", "severe bleeding", "wont stop bleeding",
    "won't stop bleeding", "bleeding won't stop", "heart attack", "stroke",
    "choking", "drowning", "anaphylaxis", "baby not breathing",
    "baby is not breathing", "stopped breathing", "cardiac arrest",
    "unresponsive", "passed out", "electrocuted", "electrical shock",
    "head injury", "skull fracture", "overdosed on pills",
]

# Keywords that make a body_symptoms detection CRITICAL (life-threatening).
LIFE_THREATENING_KEYWORDS = [
    "chest pain", "chest hurts", "chest tight", "chest tightness",
    "crushing chest", "cant breathe", "can't breathe", "trouble breathing",
    "difficulty breathing", "short of breath", "not breathing", "no pulse",
    "unconscious", "unresponsive", "not waking up", "wont wake up",
    "severe bleeding", "wont stop bleeding", "bleeding won't stop",
    "heart attack", "stroke", "choking", "drowning", "anaphylaxis",
    "seizure", "convulsion", "poison", "poisoning", "swallowed bleach",
    "swallowed chemicals", "swallowed pills", "electric shock",
    "electrocuted", "heat stroke", "hypothermia", "left arm hurts",
    "left arm pain", "numb arm", "slurred speech", "face drooping",
    "suicidal", "kill myself", "snake bite", "throat closing",
    "swollen throat", "coughing blood", "vomiting blood", "blood in vomit",
    "skull fracture", "head injury", "coma", "paralysis", "baby not breathing",
    "overdose", "overdosed", "took too many", "drug overdose", "alcohol poisoning",
    "carbon monoxide", "heater", "gas leak", "opioid overdose", "diabetic coma",
    "ketoacidosis", "low blood sugar", "low sugar", "high blood sugar",
    "high sugar", "very high sugar", "insulin reaction", "insulin shock",
    "fruity breath", "very cold", "stopped shivering", "drank too much",
    "suicide", "self harm", "self harming", "want to die", "live wire",
    "snakebite", "snake", "bitten by a snake", "whole bottle of",
    # Paraphrase-proof life threats: a stroke described as confusion or
    # slurring, a stabbing, or a fever high enough to be a real emergency.
    "confused", "confusion", "slurring", "stabbed", "high fever",
    # Disasters are life-threatening by definition: without these the banner
    # for an earthquake, flood or tsunami read "URGENT - needs attention soon"
    # above a CRITICAL row.
    "earthquake", "earth quake", "building collapse", "flood", "flooding",
    "flash flood", "rising water", "tsunami", "tidal wave", "wildfire",
    "wild fire", "forest fire", "bushfire", "on fire", "building is on fire",
    "landslide", "land slide", "mudslide", "chemical spill", "toxic spill",
    "hazmat", "power lines", "downed power lines", "live wire",
    "trapped under", "rubble", "crush injury", "lightning",
    "struck by lightning", "tornado", "hurricane", "typhoon", "cyclone",
]

# Keywords that make a medicines detection CRITICAL (overdose territory).
OVERDOSE_KEYWORDS = [
    "overdose", "overdosed", "took too many", "too many pills",
    "too many tablets", "took too much", "swallowed pills",
    "swallowed tablets", "double dose", "whole bottle of",
    "overdosed on pills", "poisoning",
]

# Words excluded from "significant token" searches (DB text matching).
STOPWORDS = {
    "the", "and", "for", "you", "your", "yours", "what", "which", "who", "whom",
    "how", "can", "cant", "cannot", "not", "have", "has", "had", "this", "that",
    "there", "where", "when", "from", "into", "over", "under", "very", "much",
    "many", "some", "any", "are", "was", "were", "will", "would", "could",
    "should", "about", "after", "before", "please", "help", "need", "want",
    "feel", "feels", "feeling", "felt", "took", "take", "taking", "taken",
    "call", "called", "number", "numbers", "which", "does", "did", "doing",
    "is", "am", "my", "me", "i", "he", "she", "they", "we", "us", "them",
    "his", "her", "its", "their", "our", "if", "or", "but", "so", "up", "down",
    "out", "off", "get", "got", "went", "been", "being", "just", "now", "then",
    "also", "too", "someone", "somebody", "something", "friend", "person",
    "man", "woman", "child", "kid", "baby", "please", "quick", "quickly",
}

# Paths — resolved relative to this file so it works from any CWD.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "db"))
DB_PATHS = {
    "emergency_numbers": os.path.join(DB_DIR, "emergency_numbers.db"),
    "medicines": os.path.join(DB_DIR, "medicines.db"),
    "body_symptoms": os.path.join(DB_DIR, "body_symptoms.db"),
}

# SQL fragment that lowercases and strips straight/curly apostrophes from a
# column, so "can't breathe" in the DB matches the normalised "cant breathe".
def _sql_norm(col):
    return "REPLACE(REPLACE(LOWER({c}), '{curly}', ''), {sq}, '')".format(
        c=col, curly="\u2019", sq="''''")

SEVERITY_RANK_SQL = ("CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'URGENT' THEN 1 "
                     "WHEN 'MODERATE' THEN 2 ELSE 3 END")

# Python mirror of the SQL severity order, for ranking result rows.
SEV_ORDER = {"CRITICAL": 0, "URGENT": 1, "MODERATE": 2}


def _normalize(text):
    """Lowercase, strip punctuation, collapse spaces, expand panic typing."""
    if not text:
        return ""
    text = text.lower().replace("\u2019", "'")
    # remove everything except letters, digits and spaces (apostrophes go too)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # panic-typing equivalents (whole words only)
    text = re.sub(r"\bim\b", "i am", text)
    text = re.sub(r"\bhes\b", "he is", text)
    text = re.sub(r"\bshes\b", "she is", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _phrase_positions(phrase, text):
    """Return list of match positions of `phrase` in `text` (word-bounded)."""
    if not phrase:
        return []
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return [m.start() for m in re.finditer(pattern, text)]


def _match_keywords(keyword_list, normalized_text):
    """Return keywords matched in `normalized_text`, ordered by appearance."""
    hits = []
    for kw in keyword_list:
        norm_kw = _normalize(kw)
        positions = _phrase_positions(norm_kw, normalized_text)
        if positions:
            hits.append((positions[0], kw))
    hits.sort(key=lambda t: t[0])
    return [kw for _, kw in hits]


def _significant_tokens(normalized_text):
    """Content words (length >= 4, not stopwords) for loose DB text search."""
    out = []
    for tok in normalized_text.split():
        if len(tok) >= 4 and tok not in STOPWORDS:
            out.append(tok)
    return out


def detect(user_input: str) -> dict:
    # --- Step 1: clean the input -------------------------------------
    cleaned = _normalize(user_input)

    # --- Step 2: critical override takes precedence ------------------
    critical_matches = _match_keywords(CRITICAL_OVERRIDE_KEYWORDS, cleaned)

    # --- Step 3: score each route ------------------------------------
    # Route scoring is deliberately tolerant (filler words, word order,
    # morphology) so a paraphrase like "pressure in my chest" or "i broke my
    # arm" still reaches the right database instead of falling to "general"
    # and being refused. The critical override above stays strict.
    body_matches = _tolerant_matches(BODY_SYMPTOM_KEYWORDS, cleaned)
    med_matches = _tolerant_matches(MEDICINE_KEYWORDS, cleaned)
    num_matches = _tolerant_matches(EMERGENCY_NUMBER_KEYWORDS, cleaned)

    scores = {
        "body_symptoms": len(body_matches),
        "medicines": len(med_matches),
        "emergency_numbers": len(num_matches),
    }

    # --- Step 4: pick the winning route ------------------------------
    # Highest score wins; ties prefer body_symptoms (highest stakes).
    best_score = max(scores.values())
    if best_score == 0:
        route = "general"
    elif scores["body_symptoms"] == best_score:
        route = "body_symptoms"
    elif scores["medicines"] == best_score:
        route = "medicines"
    else:
        route = "emergency_numbers"

    # An overdose / ingestion emergency with NO named drug is a medical
    # emergency, not a medicine-info lookup, so route it to body_symptoms.
    # If a specific drug IS named, keep the medicines route (its rows carry
    # that drug's overdose_action and antidote).
    if (route == "medicines"
            and _tolerant_matches(OVERDOSE_KEYWORDS, cleaned)
            and not _tolerant_matches(DRUG_NAME_KEYWORDS, cleaned)):
        route = "body_symptoms"

    # The mirror case: a NAMED drug with a tied score is a medicine question
    # ("is ibuprofen safe in pregnancy"), not the condition the body route
    # happened to match on a single generic word -- medicines.db is where that
    # drug's warnings and safe_in_pregnancy text live. A life-threatening
    # picture always keeps priority over a drug-info lookup.
    if (route == "body_symptoms"
            and scores["medicines"] == best_score
            and _match_keywords(DRUG_NAME_KEYWORDS, cleaned)
            and not critical_matches
            and not _tolerant_matches(LIFE_THREATENING_KEYWORDS, cleaned)):
        route = "medicines"

    # All matched keywords, in order of appearance in the message.
    combined = []
    for hits in (critical_matches, body_matches, med_matches, num_matches):
        combined.extend(hits)
    combined = sorted(set(combined), key=lambda k: _keyword_position(_normalize(k), cleaned))

    if critical_matches:
        # Return immediately: severity is locked to CRITICAL.
        return {
            "route": route if route != "general" else "body_symptoms",
            "matched_keywords": combined,
            "severity_hint": "CRITICAL",
            "critical_override": True,
        }

    # --- Step 5: severity hint ---------------------------------------
    if route == "body_symptoms":
        if _tolerant_matches(LIFE_THREATENING_KEYWORDS, cleaned):
            severity = "CRITICAL"
        else:
            severity = "URGENT"
    elif route == "medicines":
        severity = "CRITICAL" if _match_keywords(OVERDOSE_KEYWORDS, cleaned) else "MODERATE"
    elif route == "emergency_numbers":
        severity = "URGENT"
    else:
        severity = "UNKNOWN"

    return {
        "route": route,
        "matched_keywords": combined,
        "severity_hint": severity,
        "critical_override": False,
    }


def _connect(db_key):
    path = DB_PATHS[db_key]
    if not os.path.exists(path):
        raise FileNotFoundError("database not found: %s" % path)
    return sqlite3.connect(path)


def _rows_to_dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _body_part_tokens(normalized_text):
    """Body parts mentioned in the message (handles hand/hands, mouth/throat)."""
    try:
        con = _connect("body_symptoms")
        parts = [r[0] for r in con.execute("SELECT DISTINCT body_part FROM body_symptoms")]
        con.close()
    except Exception as exc:
        print("[WARN] body_part lookup failed: %s" % exc)
        return []
    words = set(normalized_text.split())
    lemmas = set()
    for w in words:
        lemmas.add(w)
        lemmas.add(w.rstrip("s"))
    found = []
    for bp in parts:
        for piece in re.split(r"[/\s]+", bp.lower()):
            if not piece:
                continue
            if piece in lemmas or piece.rstrip("s") in lemmas or (piece + "s") in lemmas:
                found.append(bp)
                break
    # Colloquial site words the DB never spells out (finger -> hands).
    for word in words:
        alias = _BODY_PART_ALIASES.get(word) or _BODY_PART_ALIASES.get(word.rstrip("s"))
        if alias and alias in parts and alias not in found:
            found.append(alias)
    return found


def _stem(token):
    """Crude suffix trim so swallowed/swallowing and burns/burning align."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[:-len(suffix)]
    return token


# Irregular verbs/nouns the suffix trimmer cannot reach: "i broke my arm"
# must connect to the stored "broken arm", "he fell" to "fall".
# NOTE: only colloquial forms are mapped, never the clinical word itself --
# mapping "fracture" -> "broken" made the single-token keyword "fracture"
# fire on any everyday use of the word ("my phone is broken").
_IRREGULAR_FORMS = {
    "broke": {"broken", "break", "fracture", "fractured"},
    "broken": {"broke", "fracture", "fractured"},
    "fell": {"fall", "fallen"},
    "fallen": {"fall", "fell"},
    "bit": {"bite", "bitten"},
    "bitten": {"bite", "bit"},
    "bled": {"bleed", "bleeding"},
    "bleed": {"bled", "bleeding"},
    "swollen": {"swelling", "swelled"},
    "swelled": {"swollen", "swelling"},
    "drank": {"drink", "drinking"},
    "ate": {"eat", "eating"},
}


# Token-level synonym bridging used ONLY for DB ranking: casual words typed
# by users ("hurts", "dizzy", "baby") must connect to the clinical words the
# dataset stores ("pain", "dizziness", "infant"), or correct rows never score.
_RANK_SYNONYMS = {
    "hurts": "pain", "hurt": "pain", "ache": "pain", "aches": "pain",
    "painful": "pain", "dizzy": "dizziness", "baby": "infant",
}

# Words that describe WHERE (left/right/upper...) or filler verbs; they are
# never counted as match evidence on their own ("left upper belly pain"
# must not match because the user said "left arm").
_POSITION_WORDS = {"left", "right", "upper", "lower", "one", "both", "side",
                   "front", "back", "inner", "outer", "stop", "wont", "cant"}

# Body parts that describe a body SYSTEM or the skin/body surface rather
# than one specific limb/site. When the user names no body part at all,
# rows from a specific limb (arm, head, leg...) are slightly demoted in
# favour of location-generic rows.
_LOCATION_GENERIC_PARTS = {"skin", "chest", "heart", "blood", "brain", "lungs",
                           "stomach", "abdomen", "liver", "kidneys",
                           "nervous system", "urinary system",
                           "reproductive system", "mouth/throat",
                           # disaster / environmental rows: they describe a
                           # situation, not a limb, so they must never lose
                           # the site-fit comparison to a specific body part.
                           "environment", "whole body"}

# Rows for the body's general surface: a safe fallback when the user names a
# site the dataset has no dedicated row for (a cut finger -- there is a
# "Deep skin laceration" row but no "finger cut" row).
_SURFACE_PARTS = {"skin", "blood"}

# Colloquial site words -> the dataset's body_part values, so "my finger is
# bleeding" still counts as a named site (the DB stores "hands").
_BODY_PART_ALIASES = {
    "finger": "hands", "fingers": "hands", "thumb": "hands",
    "palm": "hands", "wrist": "hands", "knuckle": "hands",
    "fingerprint": "hands", "fingernail": "hands", "hand": "hands",
    "arm": "arms", "leg": "legs", "foot": "feet", "feet": "feet",
    "toe": "feet", "toes": "feet", "ankle": "feet", "heel": "feet",
    "thigh": "legs", "shin": "legs", "knee": "legs", "calf": "legs",
    "belly": "abdomen", "tummy": "abdomen", "gut": "abdomen",
    "forehead": "head", "skull": "head", "scalp": "head",
    "shoulder": "arms", "elbow": "arms", "forearm": "arms",
    "eye": "eyes", "ear": "ears", "nose": "nose", "tooth": "mouth/throat",
    "gum": "mouth/throat", "tongue": "mouth/throat", "lip": "mouth/throat",
}

# Words that prove a body part was actually SEVERED. Without one of these, an
# amputation row must never be the answer to "i cut my finger" -- the amputation
# row's keywords merely contain "cut", which is enough to out-score a plain
# laceration on field repetition alone.
_AMPUTATION_EVIDENCE = (
    "off", "cut off", "severed", "amputat", "detached", "missing",
    "torn off", "hanging", "sliced off", "chopped off",
    "lost a finger", "lost a hand", "lost a toe", "lost my finger",
    "finger is gone", "came off",
)
_AMPUTATION_PENALTY = 6

# Evidence that a reaction is ANAPHYLAXIS (airway / systemic) rather than one
# locally swollen part. Checked against the message AND the row's own symptom
# text, so a genuine anaphylaxis row still wins for "throat is closing".
_ANAPHYLAXIS_EVIDENCE = (
    "throat", "airway", "swallow", "breath", "breathe", "breathing", "wheez",
    "wheez", "hives", "rash", "allergic", "allergy", "anaphyla", "sting",
    "bee", "wasp", "insect", "peanut", "nuts", "shellfish", "lips", "tongue",
    "face swelled", "face is swollen", "itching", "itchy", "collapsed",
    "trouble swallowing", "closing",
)
_ANAPHYLAXIS_PENALTY = 8

# Triage doctrine priors: symptom COMBINATIONS that point at a specific
# condition regardless of which row carries the most literal keyword hits.
# Chest pain together with breathing difficulty is treated as cardiac until
# proven otherwise, so heart-attack rows get a ranking bonus.
_CLINICAL_PRIORS = [
    ({"chest hurts", "chest pain", "crushing chest"},
     {"cant breathe", "shortness of breath", "trouble breathing",
      "hard to breathe", "difficulty breathing", "wheezing"},
     "heart attack", 6),
    # An acute INJURY that is bleeding (road accident, knife, cut, deep wound)
    # is a wound-control problem. Without this, chronic bleeding disorders
    # (haemophilia) and unrelated rows that simply repeat the word "bleeding"
    # in every field out-score the laceration rows that actually apply.
    ({"accident", "crash", "collision", "road", "knife", "stab", "stabbed",
      "gash", "cut", "deep", "fell", "wound", "injured", "injury"},
     {"bleeding", "bleeding badly", "bleeding a lot", "heavy bleeding",
      "severe bleeding", "blood loss", "wont stop bleeding"},
     ("laceration", "wound", "trauma"), 6),
    # Chest pain that RADIATES -- left arm, jaw, numbness, sweating -- is a
    # heart attack until proven otherwise. Without this prior, "my chest hurts
    # and left arm is numb" ranked Pneumothorax above Heart attack purely on
    # keyword overlap noise.
    ({"chest hurts", "chest pain", "crushing chest", "pain in chest",
      "chest pressure", "chest tight", "chest tightness", "chest squeezing"},
     {"left arm", "arm is numb", "arm pain", "numb arm", "numbness",
      "jaw pain", "jaw hurts", "sweating", "cold sweat", "radiating",
      "left arm hurts"},
     "heart attack", 8),
    # A blow to the head plus confusion or vomiting is a HEAD INJURY; the heat
    # stroke row also lists "confusion" as a symptom and used to outrank it.
    ({"hit his head", "hit her head", "hit my head", "hit their head",
      "head injury", "hit the head", "banged his head", "banged her head",
      "head trauma", "fell and hit", "fell on his head", "fell on her head"},
     {"confused", "confusion", "drowsy", "slurred", "vomiting",
      "not making sense", "disoriented", "unconscious", "not waking up"},
     ("concussion", "head injury", "skull fracture", "brain h"), 8),
    # Bleeding in pregnancy is an obstetric emergency, never a bleeding
    # disorder (the haemophilia row used to win this one).
    ({"pregnant", "pregnancy", "expecting a baby", "months pregnant"},
     {"bleeding", "blood", "spotting"},
     ("miscarriage", "ectopic", "postpartum", "umbilical", "labour"), 8),
    # Water plus an unresponsive casualty is drowning, whatever else is said.
    ({"underwater", "in the water", "submerged", "fell in water",
      "fell into water", "drowning", "near drowning", "water in lungs",
      "car underwater", "sinking"},
     {"not breathing", "unconscious", "drowning", "underwater", "water",
      "no breath", "stopped breathing"},
     ("near-drowning", "drowning"), 8),
    # Alcohol plus confusion / unconsciousness is alcohol poisoning.
    ({"alcohol", "drunk", "drank a lot", "drank too much", "beer", "vodka"},
     {"confused", "confusion", "unconscious", "passed out", "not waking up",
      "vomiting", "unresponsive"},
     ("alcohol poisoning",), 8),
    # Rodenticide is an anticoagulant poison, NOT a nerve agent -- the
    # organophosphate row used to be the answer to "swallowed rat poison".
    ({"rat poison", "rodenticide", "mouse poison", "weed killer"},
     {"swallowed", "ate", "drank", "poison", "poisoning"},
     ("rodenticide",), 8),
    # Blood from the ear after a blow to the head suggests a skull fracture.
    ({"bleeding from his ears", "bleeding from her ears", "bleeding from the ear",
      "bleeding from ears", "blood from his ear", "blood from her ear",
      "bleeding ears", "ear is bleeding", "blood in his ear"},
     {"fall", "fell", "head", "hit", "bleeding", "blood", "injury"},
     ("ear bleeding", "csf leak", "skull fracture", "head injury"), 8),
    # A stabbing / deep wound in the belly is an abdominal injury, not a chest
    # wound (both rows exist and both are CRITICAL).
    ({"stabbing", "stabbed", "stab wound", "knife", "impaled", "deep wound",
      "gash"},
     {"stomach", "abdomen", "abdominal", "belly", "gut", "tummy", "wound"},
     ("evisceration", "abdominal", "peritonitis", "internal bleeding"), 8),
    # A leg described as broken is a leg fracture (Spinal fracture used to win).
    ({"broken leg", "broke my leg", "leg looks broken", "leg is broken",
      "my leg is broken", "leg fracture", "snapped my leg", "leg is bent"},
     {"broken", "broke", "fell", "fall", "fracture", "cant walk", "wont walk"},
     ("leg fracture", "foot fracture", "compartment syndrome"), 8),
    # A neck described as broken is a spinal-cord emergency.
    ({"broke my neck", "broken neck", "neck is broken", "snapped my neck",
      "hurt my neck", "neck injury", "neck hurts", "broken back"},
     {"broke", "broken", "fell", "fall", "injury", "fracture", "cant move"},
     ("neck injury", "spinal cord", "spinal fracture"), 8),
    # A tooth knocked out of its socket is a dental emergency.
    ({"tooth knocked out", "knocked out tooth", "tooth got knocked out",
      "tooth is out", "tooth came out", "tooth fell out", "lost my tooth",
      "knocked my tooth", "knocked out a tooth"},
     {"knocked", "fell", "out", "tooth", "lost", "hit"},
     ("knocked-out tooth", "dental avulsion"), 8),
    # Sudden loss of speech and a weak arm is a stroke picture even when the
    # words "stroke", "drooping" and "slurred" are never used.
    ({"cant speak", "cant talk", "cannot speak", "cannot talk",
      "slurred speech", "face drooping", "face droop", "arm is weak",
      "arm weakness", "one side weak", "numb arm", "droopy face",
      "cant move my arm", "loss of speech"},
     {"speak", "talk", "weak", "numb", "droop", "slur", "stroke",
      "confused", "vision", "arm"},
     ("stroke", "transient ischaemic", "brain h"), 8),
    # A cord that has come out before the baby is born is a prolapsed cord.
    ({"cord came out", "cord is out", "cord hanging out", "umbilical cord",
      "cord first", "water broke", "waters broke"},
     {"pregnant", "pregnancy", "months pregnant", "labour", "labor", "baby",
      "birth", "contractions"},
     ("umbilical", "labour", "prolapsed"), 8),
    # An injury mechanism plus LOCAL swelling of that joint is a sprain --
    # "my ankle is swollen after i twisted it" must not be triaged as heart
    # failure, which simply happens to list "swollen ankles" as a symptom.
    ({"twisted my ankle", "twisted ankle", "sprained my ankle", "ankle is swollen",
      "swollen ankle", "twisted it", "rolled my ankle", "went over on my ankle"},
     {"ankle", "twisted", "sprain", "swollen", "swelling", "fell", "foot"},
     ("ankle sprain",), 8),
    # A bent back after a fall is a spinal injury, not anything else that
    # happens to share the word "fell" with the message.
    ({"back is bent", "bent back", "hurt my back", "back injury",
      "broken back", "broke my back", "back hurts", "fell on my back"},
     {"fell", "fall", "ladder", "bent", "hurt", "injury", "height",
      "stairs", "roof"},
     ("spinal fracture", "vertebral", "spinal cord", "cauda", "back"), 8),
]


def _content_tokens(norm_kw):
    """Substantive tokens of a keyword (no stopwords / position words)."""
    return [t for t in norm_kw.split()
            if len(t) >= 4 and t not in STOPWORDS and t not in _POSITION_WORDS]


def _drop_stopwords(norm_kw):
    return " ".join(t for t in norm_kw.split() if t not in STOPWORDS)


def _token_hit_count(content_toks, text):
    """How many distinct content tokens occur in `text` (word-bounded)."""
    hits = 0
    for tok in content_toks:
        if any(_phrase_positions(v, text) for v in _token_variants(tok)):
            hits += 1
    return hits


def _field_credit(phrase_vars, toks, text, weight, single_token_field=False):
    """Credit for one row field: full weight on a phrase hit (or >=2 distinct
    content tokens), weak credit for a lone token, 0 for no match."""
    if _hit_tier(phrase_vars, text):
        return weight
    hits = _token_hit_count(toks, text)
    if hits >= 2:
        return weight
    if hits == 1:
        return weight if single_token_field else 1
    return 0


def _token_variants(token):
    """Morphological + synonym + irregular variants of one normalized token,
    so stored phrases like "burnt hand" can match the user's "burned my hand"
    and "broken arm" can match "i broke my arm"."""
    irregular = _IRREGULAR_FORMS.get(token)
    if len(token) < 4 or token in STOPWORDS:
        if irregular:
            return {token} | irregular
        return {token}
    opts = {token}
    if irregular:
        opts.update(irregular)
    stem = _stem(token)
    opts.add(stem)
    opts.add(stem + "s")
    # Plural -> singular, so the dataset's "fits" / "burns" / "tablets" match
    # the user's "fit" / "burn" / "tablet". Without this "he swallowed his
    # tongue during a fit" never reached the Seizure row at all.
    if len(token) >= 4 and token.endswith("s") and not token.endswith("ss"):
        opts.add(token[:-1])
    if token.endswith("ed"):
        base = token[:-2]
        opts.update({base, base + "t", base + "ing"})
    if token.endswith("ing"):
        base = token[:-3]
        opts.update({base, base + "t", base + "ed"})
    if token.endswith("e"):
        base = token[:-1]
        opts.update({base, base + "ing", base + "ed"})
    else:
        opts.add(token + "ing")
    syn = _RANK_SYNONYMS.get(token)
    if syn:
        opts.add(syn)
    return opts


def _keyword_variants(norm_kw):
    """Phrase-level variants of a matched keyword (cartesian product of the
    token variants, capped) used for word-bounded matching against row text."""
    tokens = norm_kw.split()
    if not tokens:
        return set()
    combos = {()}
    for tok in tokens:
        nxt = set()
        for partial in combos:
            for opt in _token_variants(tok):
                nxt.add(partial + (opt,))
        combos = nxt
        if len(combos) > 64:
            break
    return {" ".join(c) for c in combos if c} | {norm_kw}


def _flex_positions(phrase, text):
    """Word-bounded match of a phrase allowing ONE filler word between its
    own words ("baby is not breathing" matches "baby not breathing")."""
    words = phrase.split()
    if len(words) < 2:
        return []
    gap = r"(\s+[a-z0-9]+)?"
    pattern = (r"(?<![a-z0-9])" + gap.join(re.escape(w) for w in words)
               + r"(?![a-z0-9])")
    return [m.start() for m in re.finditer(pattern, text)]


def _hit_tier(variants, text):
    """None / 'single' / 'multi' — how strongly a keyword's variants occur
    in `text` (word-bounded). Multi-token variants may match with one filler
    word between their words; single tokens only match contiguously."""
    for v in sorted(variants, key=len, reverse=True):
        if " " in v and (_phrase_positions(v, text) or _flex_positions(v, text)):
            return "multi"
    for v in variants:
        if " " not in v and _phrase_positions(v, text):
            return "single"
    return None


# ----------------------------------------------------------------------
# Route-level tolerant matching
# ----------------------------------------------------------------------
# The strict phrase matcher needs the user's words to appear exactly as
# stored ("chest pressure"). Real messages say "pressure in my chest",
# "my heart is racing", "i broke my arm", "my child swallowed bleach".
# These helpers add tolerance for ROUTE selection (which database to open)
# and for the SEVERITY hint, so a paraphrase still reaches the right table:
#   1. morphology / synonyms / irregulars -- broke -> broken, hurts -> pain
#   2. one filler word        -- "baby is not breathing" ~ "baby not breathing"
#   3. free word order        -- "chest pressure" ~ "pressure in my chest"
# The CRITICAL_OVERRIDE list stays strict: a stray word must never be able
# to fake a CRITICAL short-circuit.
# ----------------------------------------------------------------------
def _route_required_tokens(norm_kw):
    """Significant words of a keyword (filler/stopwords removed) that must
    ALL be present for a free-word-order match. Short body words (arm, eye,
    jaw, cut) are kept, and position words (left, right) are kept too, so
    "my right arm hurts" can never match "left arm hurts"."""
    return [t for t in norm_kw.split()
            if len(t) >= 3 and t not in STOPWORDS]


def _window_match(required_tokens, text, extra_gap=2):
    """True when every required token (with its morphology/synonym variants)
    occurs inside one small sliding window, in ANY order and with up to
    `extra_gap` filler words between them. Single-token keywords are not
    free-ordered (they are already handled by the strict matcher)."""
    if len(required_tokens) < 2:
        return False
    targets = [_token_variants(t) for t in required_tokens]
    needed = len(targets)
    words = text.split()
    span = needed + extra_gap
    for i in range(len(words)):
        found = set()
        for word in words[i:i + span]:
            for k, opts in enumerate(targets):
                if k not in found and word in opts:
                    found.add(k)
        if len(found) == needed:
            return True
    return False


def _keyword_position(norm_kw, text):
    """Approximate character position of a keyword's first match, so
    tolerated matches can still be ordered by where they appeared."""
    pos = _phrase_positions(norm_kw, text)
    if pos:
        return pos[0]
    for variant in sorted(_keyword_variants(norm_kw), key=lambda v: (-len(v), v)):
        hits = _phrase_positions(variant, text) or _flex_positions(variant, text)
        if hits:
            return hits[0]
    required = _route_required_tokens(norm_kw)
    if len(required) >= 2:
        targets = [_token_variants(t) for t in required]
        needed = len(targets)
        words = text.split()
        span = needed + 2
        offset = 0
        for i in range(len(words)):
            found = set()
            for word in words[i:i + span]:
                for k, opts in enumerate(targets):
                    if k not in found and word in opts:
                        found.add(k)
            if len(found) == needed:
                return offset
            offset += len(words[i]) + 1
    return 10 ** 6


def _tolerant_matches(keyword_list, text):
    """Keywords present in `text` permissively: strict phrase, then
    morphology + one filler word, then free word order."""
    hits = []
    for kw in keyword_list:
        norm_kw = _normalize(kw)
        if not norm_kw:
            continue
        matched = bool(_phrase_positions(norm_kw, text))
        if not matched and _hit_tier(_keyword_variants(norm_kw), text):
            matched = True
        if not matched and _window_match(_route_required_tokens(norm_kw), text):
            matched = True
        if matched:
            hits.append((_keyword_position(norm_kw, text), kw))
    hits.sort(key=lambda t: t[0])
    return [kw for _, kw in hits]


def _query_body_symptoms(det, user_input):
    normalized = _normalize(user_input)
    norm_kws = [_normalize(k) for k in det["matched_keywords"] if _normalize(k)]
    mentioned = set(_body_part_tokens(normalized))
    # Colloquial site words ("ankle", "finger", "leg") map onto the dataset's
    # body_part values ("feet", "hands", "legs") so that a named site always
    # counts in the site-fit comparison -- "my ankle is swollen after i twisted
    # it" used to be answered by the Anaphylaxis row.
    for word in normalized.split():
        alias = _BODY_PART_ALIASES.get(word)
        if alias:
            mentioned.add(alias)

    # Triage priors fire on the message as a whole (e.g. chest pain AND
    # breathing difficulty together), independent of individual rows. They are
    # computed BEFORE the database search because a fired prior also PULLS the
    # clinically indicated row into the candidate pool: "i am stuck in a car
    # underwater" only shared the word "underwater" with rows that have nothing
    # to do with drowning, so the Near-drowning row was never even scored.
    # Trigger matching is tolerant (morphology, one filler word, free word
    # order) so "leg looks broken" and "leg is broken" fire the same prior.
    fired_priors = []
    for pain_trigs, breath_trigs, cond_term, bonus in _CLINICAL_PRIORS:
        if (_tolerant_matches(list(pain_trigs), normalized)
                and _tolerant_matches(list(breath_trigs), normalized)):
            fired_priors.append((cond_term, bonus))

    prior_terms = []
    for cond_term, _bonus in fired_priors:
        prior_terms.extend(cond_term if isinstance(cond_term, tuple)
                           else (cond_term,))

    # STEP 1 — collect ALL candidate matches. LIKE runs on the keyword
    # variants (burned/burnt/burn, hurts/pain, ...) across keywords,
    # condition and symptoms, plus any body part named in the message.
    conditions, params = [], []
    for kw in norm_kws:
        # The trailing `v` matters: _keyword_variants returns a SET, so with
        # equal (space-count, length) the order depended on string hashing and
        # the 8 kept variants changed from process to process. That silently
        # changed the candidate pool and therefore the answer ("i spilled
        # boiling water on my arm" answered with the Flood row in roughly one
        # run out of six). Sorting on the variant text makes it reproducible.
        variants = sorted(_keyword_variants(kw),
                          key=lambda v: (v.count(" "), len(v), v))[:8]
        for col in ("keywords", "condition", "symptoms"):
            for var in variants:
                conditions.append(_sql_norm(col) + " LIKE ?")
                params.append("%" + var + "%")

    # Rows for a body part the user named are fetched SEPARATELY and merged
    # afterwards. They must not count as "the keyword search found something":
    # doing so suppressed the loose search below, and an input whose only
    # keyword hits were stemmed variants ("i spilled boiling water on my arm"
    # -> "boil water", "boilt water", ...) then returned NO rows at all even
    # though the Scald row carries "boiling water" verbatim.
    bp_conditions, bp_params = [], []
    for bp in mentioned:
        bp_conditions.append("body_part = ?")
        bp_params.append(bp)

    con = _connect("body_symptoms")
    try:
        candidates = []
        if conditions:
            candidates = _rows_to_dicts(con.execute(
                "SELECT * FROM body_symptoms WHERE " + " OR ".join(conditions), params))

        # Fallback: the whole keyword phrase is missing from every row, even
        # though its words are there in another order or wording (the message
        # "heater fumes" vs the stored "faulty heater" / "exhaust fumes").
        # These candidates are then SCORED exactly like the primary ones --
        # returning them pre-sorted by severity alone used to put an unrelated
        # CRITICAL row ("CSF leak", matched only on the word "leaking") on top.
        loose_search = False
        if not candidates:
            fb_conds, fb_params = [], []
            for tok in _significant_tokens(normalized):
                stem = _stem(tok)
                if len(stem) < 4:
                    continue
                for col in ("keywords", "condition", "symptoms"):
                    fb_conds.append(_sql_norm(col) + " LIKE ?")
                    fb_params.append("%" + stem + "%")
            if not fb_conds:
                return []
            candidates = _rows_to_dicts(con.execute(
                "SELECT * FROM body_symptoms WHERE " + " OR ".join(fb_conds), fb_params))
            loose_search = True

        # Now add the named body part's rows to the pool (after the fallback
        # decision above, so they can never mask it).
        if bp_conditions:
            have = {r.get("id") for r in candidates}
            for row in _rows_to_dicts(con.execute(
                    "SELECT * FROM body_symptoms WHERE "
                    + " OR ".join(bp_conditions), bp_params)):
                if row.get("id") not in have:
                    candidates.append(row)

        # Rows named by a fired triage prior always join the pool, even when
        # the user's wording shares no keyword with them.
        pulled_ids = set()
        if prior_terms:
            where = " OR ".join("LOWER(condition) LIKE ?" for _ in prior_terms)
            extra = _rows_to_dicts(con.execute(
                "SELECT * FROM body_symptoms WHERE " + where,
                ["%" + t + "%" for t in prior_terms]))
            have = {r.get("id") for r in candidates}
            for row in extra:
                if row.get("id") not in have:
                    candidates.append(row)
                    pulled_ids.add(row.get("id"))
    finally:
        con.close()

    # Deduplicate overlapping keywords so a short keyword contained in a
    # longer one ("burned" inside "burned my hand") cannot double-count.
    kept_kws = []
    for kw in norm_kws:
        toks = _content_tokens(kw) or kw.split()
        covered = False
        for prev in kept_kws:
            ptoks = _content_tokens(prev) or prev.split()
            for i in range(len(ptoks) - len(toks) + 1):
                if ptoks[i:i + len(toks)] == toks:
                    covered = True
                    break
            if covered:
                break
        if not covered:
            kept_kws.append(kw)

    # (Triage priors were computed above, before the database search -- they
    # decide which rows are even allowed into the candidate pool.)

    # A body part was actually severed, or the amputation rows are demoted.
    amputation_evidenced = any(
        _phrase_positions(w, normalized) for w in _AMPUTATION_EVIDENCE)

    # STEP 2 — score each row for relevance (spec weights: keyword +2,
    # symptom +3, condition +4, body part +2; CRITICAL +5, URGENT +2).
    # Matching is two-level: first the whole keyword phrase (morphological
    # variants, stopwords dropped, one filler word allowed), then its
    # content tokens ("burned my hand" -> hand + burn). A lone token in a
    # condition name counts only +1 so a generic word like "arm" inside
    # "Stroke (arm weakness)" cannot outweigh a real symptom hit. Rows are
    # ranked by TOTAL score — evidence and severity boost together — not
    # by severity or row order, which is what puts the scenario the user
    # actually described at the top.
    scored = []
    for row in candidates:
        hay = {
            "kw": _normalize(row.get("keywords") or ""),
            "cond": _normalize(row.get("condition") or ""),
            "sym": _normalize(row.get("symptoms") or ""),
            "bp": _normalize(row.get("body_part") or ""),
        }
        evidence = 0
        for kw in kept_kws:
            phrase_vars = _keyword_variants(kw)
            dropped = _drop_stopwords(kw)
            if dropped and dropped != kw:
                phrase_vars = phrase_vars | _keyword_variants(dropped)
            toks = _content_tokens(kw)
            evidence += _field_credit(phrase_vars, toks, hay["kw"], 2)
            evidence += _field_credit(phrase_vars, toks, hay["sym"], 3)
            evidence += _field_credit(phrase_vars, toks, hay["cond"], 4)
            # body_part is a single word, so one token hit is full credit
            evidence += _field_credit(phrase_vars, toks, hay["bp"], 2, True)
        pulled = row.get("id") in pulled_ids
        if evidence <= 0:
            # A prior-pulled row is kept even without keyword overlap: a fired
            # triage rule IS the evidence (the message said "underwater", the
            # row is Near-drowning, no shared word required).
            if pulled:
                evidence = 1
            else:
                continue
        sev = row.get("severity")
        row_bp = row.get("body_part") or ""
        score = evidence + (5 if sev == "CRITICAL" else 2 if sev == "URGENT" else 0)

        # SITE FIT. When the user names a body part, rows for a DIFFERENT
        # specific site are demoted and rows for the body's general surface
        # (skin/blood) act as the fallback. When no part is named, the old
        # "prefer location-generic rows" demotion applies unchanged.
        if mentioned:
            if row_bp in mentioned:
                site_rank = 0
            elif row_bp in _SURFACE_PARTS:
                site_rank = 1
            elif row_bp in _LOCATION_GENERIC_PARTS:
                site_rank = 2
            else:
                site_rank = 3
                score -= 1
        elif row_bp in _SURFACE_PARTS:
            # No part named: a body-surface row is the safest general answer
            # ("i cut myself" -> Deep skin laceration, not "Lip or tongue").
            site_rank = 0
        elif row_bp in _LOCATION_GENERIC_PARTS:
            site_rank = 1
        else:
            site_rank = 2
            score -= 1

        # An amputation row needs proof that a part was actually severed.
        cond_l = (row.get("condition") or "").lower()
        if "amputat" in cond_l and not amputation_evidenced:
            score -= _AMPUTATION_PENALTY

        # ANAPHYLAXIS OVER-TRIAGE GUARD. The anaphylaxis rows are CRITICAL and
        # share the word "swollen"/"swelling" with ordinary local swelling, so
        # "my ankle is swollen after i twisted it" was answered with
        # anaphylaxis. Anaphylaxis needs evidence of an AIRWAY or SYSTEMIC
        # reaction, not just one swollen part.
        if "anaphyla" in cond_l or "throat swelling" in cond_l:
            if not any(_phrase_positions(t, normalized)
                       for t in _ANAPHYLAXIS_EVIDENCE):
                score -= _ANAPHYLAXIS_PENALTY

        # Triage priors (e.g. chest pain + breathlessness -> heart attack).
        for cond_term, bonus in fired_priors:
            terms = cond_term if isinstance(cond_term, tuple) else (cond_term,)
            if any(t in cond_l for t in terms):
                score += bonus
                break

        scored.append((-score, site_rank, SEV_ORDER.get(sev, 3), row.get("id", 0), row))

    # STEP 3 — sort by score descending (then site fit, severity, id), top 3.
    scored.sort(key=lambda t: t[:4])
    if not scored and loose_search:
        # Last resort: keep the loose matches (severity order) so a caller
        # still receives something rather than nothing.
        candidates.sort(key=lambda r: (SEV_ORDER.get(r.get("severity"), 3), r.get("id", 0)))
        for row in candidates[:3]:
            row["_score"] = 0
        return candidates[:3]
    top = [t[4] for t in scored[:3]]
    for neg_score, _site, _sev, _id, row in scored[:3]:
        # Expose the winning rank score (tests and debugging; additive only).
        row["_score"] = -neg_score
    return top


def _query_medicines(det, user_input):
    """Pull the medicine rows that actually answer the question.

    This used to be `SELECT ... LIMIT 3` in table order, so the returned rows
    had nothing to do with relevance: "what is the antidote for warfarin
    overdose" answered with Fentanyl, "double dose of metformin" answered with
    Aspirin and "alcohol with diazepam" answered with Codeine -- whichever row
    happened to sit earlier in the table. Candidates are now SCORED, with the
    drug the user actually named weighted far above incidental word matches
    ("dose", "tablets", "expired") that appear in many rows' text.
    """
    normalized = _normalize(user_input)
    tokens = _significant_tokens(normalized)
    conditions, params = [], []

    for tok in tokens:
        conditions.append(
            "(LOWER(medicine_name) LIKE ? OR LOWER(aliases) LIKE ? "
            "OR LOWER(category) LIKE ? OR LOWER(used_for) LIKE ? "
            "OR LOWER(warnings) LIKE ? OR LOWER(max_dose_child) LIKE ?)")
        params.extend(["%" + tok + "%"] * 6)

    for kw in det["matched_keywords"]:
        norm_kw = _normalize(kw)
        if norm_kw:
            conditions.append(
                "(LOWER(used_for) LIKE ? OR LOWER(category) LIKE ? "
                "OR LOWER(aliases) LIKE ?)")
            params.extend(["%" + norm_kw + "%"] * 3)

    if not conditions:
        return []

    con = _connect("medicines")
    try:
        rows = _rows_to_dicts(con.execute(
            "SELECT * FROM medicines WHERE " + " OR ".join(conditions), params))
    finally:
        con.close()
    if not rows:
        return []

    # The drugs the user actually named -- generic OR brand name.
    named = []
    for kw in _tolerant_matches(DRUG_NAME_KEYWORDS, normalized):
        nk = _normalize(kw)
        if nk and nk not in named:
            named.append(nk)

    scored = []
    for row in rows:
        name = _normalize(row.get("medicine_name") or "")
        aliases = _normalize(row.get("aliases") or "")
        category = _normalize(row.get("category") or "")
        used = _normalize(row.get("used_for") or "")
        warnings = _normalize(row.get("warnings") or "")
        child_dose = _normalize(row.get("max_dose_child") or "")
        score = 0

        for drug in named:
            variants = _token_variants(drug)
            if (_phrase_positions(drug, name)
                    or any(_phrase_positions(v, name) for v in variants)):
                score += 12          # the named drug itself
            elif any(_phrase_positions(v, aliases) for v in variants):
                score += 10          # a brand name / synonym of it
            elif (_phrase_positions(drug, category)
                    or _phrase_positions(drug, used)):
                score += 6           # a drug of that class

        for tok in tokens:
            variants = _token_variants(tok)
            if any(_phrase_positions(v, name) for v in variants):
                score += 6
            elif any(_phrase_positions(v, aliases) for v in variants):
                score += 4
            elif (any(_phrase_positions(v, category) for v in variants)
                    or any(_phrase_positions(v, used) for v in variants)):
                score += 2
            elif (any(_phrase_positions(v, warnings) for v in variants)
                    or any(_phrase_positions(v, child_dose) for v in variants)):
                score += 2

        if score <= 0:
            continue
        scored.append((-score, row.get("id", 0), row))

    scored.sort(key=lambda t: t[:2])
    top = [t[2] for t in scored[:3]]
    for neg_score, _id, row in scored[:3]:
        # Expose the ranking score for tests / debugging (see query_with_scores
        # usage in test_db_llm.py). It is additive and ignored by the UI.
        row["_score"] = -neg_score
    return top


# Everyday names people actually type for countries whose DB name is longer
# or different ("uk", "usa", "uae", "holland"). Without these the message
# "emergency number in uae" fell through to the top-5 fallback list and the
# user was read the numbers of the WRONG country.
_COUNTRY_ALIASES = {
    "uk": "United Kingdom", "u.k": "United Kingdom",
    "britain": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "usa": "United States of America", "u.s.a": "United States of America",
    "us": "United States of America", "u.s": "United States of America",
    "america": "United States of America",
    "united states": "United States of America",
    "uae": "United Arab Emirates", "emirates": "United Arab Emirates",
    "holland": "Netherlands", "burma": "Myanmar",
    "south korea": "Republic of Korea", "korea": "Republic of Korea",
    "north korea": "Democratic People's Republic of Korea",
    "czechia": "Czech Republic", "macedonia": "North Macedonia",
    "swaziland": "Eswatini", "vatican": "Vatican City",
    "holy see": "Vatican City", "russia": "Russia",
    "ivory coast": "Cote d'Ivoire", "drc": "Democratic Republic of the Congo",
    "congo": "Republic of the Congo", "somaliland": "Somalia",
    "bosnia": "Bosnia and Herzegovina", "trinidad": "Trinidad and Tobago",
    "st lucia": "Saint Lucia", "antigua": "Antigua and Barbuda",
}


def _detect_country(user_input):
    """Best-effort country detection from the user's message (name, alias or
    ISO code).

    Ranking (highest wins), each level more specific than the next:
      1. longest country name written out in full inside the message
      2. longest country-name PREFIX matching the message word for word
         ("united states" -> United States of America, NOT the Virgin
         Islands entry that a bare SQL LIKE could return first)
      3. the alias table above ("uk", "usa", "uae", ...)
      4. an explicit 2-letter ISO code
    A partial single-word LIKE ("united") is deliberately NOT used any more:
    it used to pick an arbitrary country whose name merely contains the word.
    """
    normalized = _normalize(user_input)
    words = normalized.split()
    if not words:
        return None
    try:
        con = _connect("emergency_numbers")
    except Exception as exc:
        print("[WARN] country detection failed: %s" % exc)
        return None
    try:
        names = [r[0] for r in con.execute("SELECT country FROM emergency_numbers")]

        # 1) a whole country name appears in the message
        full = []
        for name in names:
            if _phrase_positions(_normalize(name), normalized):
                full.append(name)
        if full:
            full.sort(key=len, reverse=True)
            return full[0]

        # 2) word-aligned prefix: the longest run of leading country-name
        # words that also appears as a run of words in the message. Only runs
        # of 2+ words qualify (a single word is already covered by step 1),
        # which is what stops "united" from picking an arbitrary territory.
        # Ties prefer the SHORTER name -- the plain country entry.
        best = None  # (run_length, -len(name), name)
        for name in names:
            nwords = _normalize(name).split()
            for k in range(min(len(nwords), len(words)), 1, -1):
                prefix = nwords[:k]
                if any(words[i:i + k] == prefix
                       for i in range(len(words) - k + 1)):
                    cand = (k, -len(name), name)
                    if best is None or cand > best:
                        best = cand
                    break
        if best:
            return best[2]

        # 3) everyday aliases (longest phrase first, word-bounded)
        for alias in sorted(_COUNTRY_ALIASES, key=len, reverse=True):
            if _phrase_positions(_normalize(alias), normalized):
                target = _COUNTRY_ALIASES[alias]
                row = con.execute(
                    "SELECT country FROM emergency_numbers WHERE LOWER(country) = ?",
                    (target.lower(),)).fetchone()
                if row:
                    return row[0]
                for name in names:
                    if name.lower().startswith(target.lower()):
                        return name

        # 4) explicit 2-letter country code (skip stopwords like "in")
        stop2 = {"in", "is", "it", "to", "do", "of", "on", "at", "be", "by",
                 "my", "me", "we", "he", "no", "so", "up", "if", "as", "an",
                 "or", "im", "am", "us"}
        for tok in words:
            if len(tok) == 2 and tok not in stop2:
                row = con.execute(
                    "SELECT country FROM emergency_numbers WHERE LOWER(country_code) = ?",
                    (tok,)).fetchone()
                if row:
                    return row[0]
        return None
    finally:
        con.close()


def _query_emergency_numbers(det, user_input):
    con = _connect("emergency_numbers")
    try:
        country = _detect_country(user_input)
        if country:
            cur = con.execute("SELECT * FROM emergency_numbers WHERE country = ?", (country,))
            rows = _rows_to_dicts(cur)
            if rows:
                return rows
        # Fallback: top 5 most commonly needed countries.
        fallback = ["United States", "United Kingdom", "Pakistan", "India", "Australia"]
        rows = []
        for name in fallback:
            cur = con.execute(
                "SELECT * FROM emergency_numbers WHERE country LIKE ? LIMIT 1",
                (name + "%",))
            rows.extend(_rows_to_dicts(cur))
        return rows
    finally:
        con.close()


def query_db(detection_result: dict, user_input: str) -> dict:
    route = detection_result.get("route", "general")
    results = []

    if route != "general":
        try:
            if route == "body_symptoms":
                results = _query_body_symptoms(detection_result, user_input)
            elif route == "medicines":
                results = _query_medicines(detection_result, user_input)
            elif route == "emergency_numbers":
                results = _query_emergency_numbers(detection_result, user_input)
        except Exception as exc:
            # Never crash — log a warning and return whatever we have.
            print("[WARN] query failed for route '%s': %s" % (route, exc))
            results = []

    return {
        "route": route,
        "severity_hint": detection_result.get("severity_hint", "UNKNOWN"),
        "critical_override": detection_result.get("critical_override", False),
        "db_results": results,
        "db_result_count": len(results),
    }


def run(user_input: str) -> dict:
    detection = detect(user_input)
    return query_db(detection, user_input)


if __name__ == "__main__":
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
    expected_routes = [
        "body_symptoms",
        "body_symptoms",
        "medicines",
        "emergency_numbers",
        "body_symptoms",
        "body_symptoms",
        "body_symptoms",
        "emergency_numbers",
        "body_symptoms",
        "body_symptoms",
    ]
    expected_critical = [False, True, False, False, True, True, False, False, False, False]

    def top_label(result):
        rows = result["db_results"]
        if not rows:
            return "(none)"
        row = rows[0]
        for key in ("condition", "medicine_name", "country"):
            if key in row:
                return row[key]
        return "(unknown)"

    correct_routes = 0
    critical_ok = 0
    db_returned = 0
    issues = []

    for i, text in enumerate(test_cases):
        result = run(text)
        override = result["critical_override"]
        print('INPUT: "%s"' % text)
        print("ROUTE: %s" % result["route"])
        print("SEVERITY: %s" % result["severity_hint"])
        print("CRITICAL OVERRIDE: %s" % override)
        print("DB RESULTS COUNT: %s" % result["db_result_count"])
        print("TOP RESULT CONDITION: %s" % top_label(result))
        print("-" * 40)

        if result["route"] == expected_routes[i]:
            correct_routes += 1
        else:
            issues.append("wrong route for %r: got %s, expected %s" %
                          (text, result["route"], expected_routes[i]))

        if override == expected_critical[i]:
            critical_ok += 1 if override else 0
        else:
            issues.append("critical override mismatch for %r: got %s, expected %s" %
                          (text, override, expected_critical[i]))

        if result["db_result_count"] > 0:
            db_returned += 1
        else:
            issues.append("no DB results for %r (route=%s)" % (text, result["route"]))

    status = "READY" if not issues else "NEEDS FIXES"
    report_lines = [
        "---KEYWORD DETECTOR TEST REPORT---",
        "Tests run: %d" % len(test_cases),
        "Correct routes: %d/%d" % (correct_routes, len(test_cases)),
        "CRITICAL overrides fired correctly: %d" % critical_ok,
        "DB results returned: %d/%d queries returned results" % (db_returned, len(test_cases)),
        "Issues found: %s" % ("none" if not issues else "; ".join(issues)),
        "Status: %s" % status,
        "---DONE---",
    ]
    report_text = "\n".join(report_lines) + "\n"
    print(report_text)
    try:
        with open(os.path.join(BASE_DIR, "test_report.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(report_text)
        print("report written -> %s" % os.path.join(BASE_DIR, "test_report.txt"))
    except Exception as exc:
        print("[WARN] could not write test_report.txt: %s" % exc)
