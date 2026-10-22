import sqlite3
import requests
import os
import re
import sys
import unicodedata

# ── CONFIG ──────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:1.5b"
DB_ROOT = "db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _detector_top_row(user_input, route):
    """The top verified row the app's own detector picks for this message.

    keyword_detector/keywords.py already ranks rows (morphology, site fit,
    triage priors, severity) and has its own test suite, so where it has an
    answer this script uses it: the chat script and the shipped pipeline can
    then never disagree about what a message is about. Nothing here depends on
    it - if the import or the detector fails, or it routes the message
    elsewhere, the local searches below answer instead.
    """
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from keyword_detector.keywords import run as detect_and_query
        result = detect_and_query(user_input)
        if result.get("route") != route:
            return None
        rows = result.get("db_results") or []
        return rows[0] if rows else None
    except Exception:
        return None

# ── DB QUERIES ───────────────────────────────────
# Words that carry no medical meaning on their own. Matched against a whole
# row they only create false hits, and they used to decide the search ("the"
# matched ANY row containing those three letters).
SENTENCE_STOPWORDS = {
    "the","and","for","with","from","that","this","what","whats",
    "should","could","would","have","has","had","was","were","are",
    "you","your","his","her","him","she","they","them","been","being",
    "badly","very","much","more","most","about","there","here","when",
    "then","than","into","onto","over","under","after","before","again",
    "still","just","like","some","any","all","one","two","its","me",
    "my","is","in","on","of","to","do","did","does","how","can",
    "not","no","a","an","at","by","be","am","it","someone",
    "somebody","person","help","please","get","got","getting","ive",
    "im","dont","cant","also","but","or","if","tell","know","need",
    "took","take","taking","taken","give","gave","given","ate","eat",
    "eaten","swallowing","much","many","some","only","even","make",
    "made","went","come","came","says","said","feel","feels","feeling",
}


def _word_variants(word):
    """The word plus the simple stems a database row is likely to store:
    "stabbed" -> stab, "crushed" -> crush, "drowning" -> drown."""
    forms = {word}
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            forms.add(word[:-len(suffix)])
    if word.endswith("ed") and len(word) > 5:   # doubled consonant, e.g. stabb
        forms.add(word[:-3])
    return forms


def _row_tokens(row_text):
    """The words of a database field. Matching on whole words (allowing a
    stored word to be LONGER: "numb" finds "numbness") is what stops the
    noise a bare LIKE produces - the word "rat" used to match "tartrate",
    "nitrate" and "Clarityne", and "cut" matched "electrocution"."""
    return [t for t in re.split(r"[^a-z0-9']+", (row_text or "").lower()) if t]


def _token_hit(tokens, variant):
    return any(t == variant or t.startswith(variant) for t in tokens)


def _content_words(user_input):
    """The words of a sentence that are worth searching the database for."""
    words = []
    for raw in user_input.lower().split():
        word = raw.strip(".,!?;:\"'()[]{}")
        if len(word) < 3 or word in SENTENCE_STOPWORDS:
            continue
        words.append(word)
    return words


def query_body_symptoms(user_input):
    """Best body_symptoms row for a whole sentence."""
    return (_detector_top_row(user_input, "body_symptoms")
            or _word_search_body_symptoms(user_input))


def _word_search_body_symptoms(user_input):
    """Word-by-word fallback for wording the detector's vocabulary lacks.

    The old version pasted the ENTIRE sentence into one LIKE
    ("%My arm is badly injured by a bullet%"), which can only match a row that
    contains that exact sentence - so multi-word input matched nothing at all
    and every real question fell through to the LLM alone. Input is now
    searched word by word (with simple stem variants), then every candidate row
    is scored on the words that actually appear in it, and the highest score
    wins.
    """
    words = _content_words(user_input)
    if not words:
        return None

    db = sqlite3.connect(f"{DB_ROOT}/body_symptoms.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    candidates = {}
    for word in words:
        for variant in _word_variants(word):
            cur.execute("""
                SELECT * FROM body_symptoms
                WHERE LOWER(keywords)  LIKE ?
                   OR LOWER(symptoms)  LIKE ?
                   OR LOWER(condition) LIKE ?
                   OR LOWER(body_part) LIKE ?
            """, (f"%{variant}%",) * 4)
            for row in cur.fetchall():
                candidates[row['id']] = dict(row)
    db.close()

    if not candidates:
        return None

    best_row = None
    best_score = -1
    for r in candidates.values():
        fields = {name: _row_tokens(r.get(name))
                  for name in ('condition', 'symptoms', 'keywords', 'body_part')}
        score = 0
        for word in words:
            for variant in _word_variants(word):
                if _token_hit(fields['condition'], variant): score += 4
                if _token_hit(fields['symptoms'], variant):  score += 3
                if _token_hit(fields['keywords'], variant):  score += 2
                if _token_hit(fields['body_part'], variant): score += 2
        if r.get('severity') == 'CRITICAL': score += 3
        elif r.get('severity') == 'URGENT': score += 1
        if score > best_score:
            best_score = score
            best_row = r
    return best_row

def query_medicine(user_input):
    """Best medicines row for a whole sentence.

    The old version took the FIRST row any word of the sentence matched, in
    the order the words were typed, across the used_for column too. "can i
    give ibuprofen to a pregnant woman" matched the word "can" against
    "cancer pain" and answered with Morphine; "i took too much ibuprofen"
    answered Paracetamol. The detector decides first; the fallback searches
    only the drug's name and its aliases, longest word first, so a long,
    specific drug name can never lose to a short filler word.
    """
    row = _detector_top_row(user_input, "medicines")
    if row is not None:
        return row

    words = sorted(_content_words(user_input), key=len, reverse=True)
    db = sqlite3.connect(f"{DB_ROOT}/medicines.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    for word in words:
        for variant in _word_variants(word):
            cur.execute("""
                SELECT * FROM medicines
                WHERE LOWER(COALESCE(medicine_name,'')) LIKE ?
                OR LOWER(COALESCE(aliases,'')) LIKE ?
            """, (f"%{variant}%",) * 2)
            for row in cur.fetchall():
                tokens = _row_tokens((row['medicine_name'] or '') + " "
                                     + (row['aliases'] or ''))
                if _token_hit(tokens, variant):
                    db.close()
                    return dict(row)
    db.close()
    return None

# Two-letter country codes that are also ordinary English words. "in" and
# "me" appear in questions like "what number do i call in an emergency", and
# matching them scored India and Montenegro over the real country - the same
# class of bug as "the" matching "The Bahamas".
COMMON_WORD_CODES = {
    "in", "me", "my", "no", "it", "so", "is", "as", "at", "am", "an",
    "or", "of", "on", "by", "be", "we", "he", "do", "to", "us", "if",
    "la", "ma", "pa", "de", "id", "ms", "tv", "ok", "pm", "cm", "ft",
}


def _fold(text):
    """Lowercase, accent-free form used for every country comparison, so a
    user typing "cote d'ivoire" matches the stored "Côte d'Ivoire"."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    ).lower()


def query_emergency_numbers(user_input):
    """Which country is this question about?

    The old version looped over every word of the input and ran one LIKE per
    word, taking the FIRST row the database happened to return. "whats the
    ambulance number in dubai" therefore matched the word "the" against
    "The Bahamas" and answered 911 - wrong country, wrong number. Adjectives
    ("pakistani" vs "Pakistan") and cities ("dubai" vs "United Arab Emirates")
    did not match at all.
    """
    db = sqlite3.connect(f"{DB_ROOT}/emergency_numbers.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # Load all countries from DB
    cur.execute(
        "SELECT country, country_code FROM emergency_numbers"
    )
    all_countries = cur.fetchall()

    # Map adjective forms and city names to country names
    name_map = {
        # Adjective forms
        "pakistani":    "pakistan",
        "indian":       "india",
        "nigerian":     "nigeria",
        "american":     "united states of america",
        "british":      "united kingdom",
        "australian":   "australia",
        "canadian":     "canada",
        "german":       "germany",
        "french":       "france",
        "dutch":        "netherlands",
        "saudi":        "saudi arabia",
        "emirati":      "united arab emirates",
        "bangladeshi":  "bangladesh",
        "turkish":      "turkey",
        "egyptian":     "egypt",
        "iranian":      "iran",
        "iraqi":        "iraq",
        "afghan":       "afghanistan",
        "chinese":      "people's republic of china",
        "japanese":     "japan",
        "korean":       "republic of korea",
        "brazilian":    "brazil",
        "mexican":      "mexico",
        "spanish":      "spain",
        "italian":      "italy",
        "russian":      "russia",
        "indonesian":   "indonesia",
        "malaysian":    "malaysia",
        "thai":         "thailand",
        "filipino":     "philippines",
        "kenyan":       "kenya",
        "ghanaian":     "ghana",
        "ethiopian":    "ethiopia",
        "moroccan":     "morocco",
        "algerian":     "algeria",
        "lebanese":     "lebanon",
        "syrian":       "syria",
        "jordanian":    "jordan",
        "kuwaiti":      "kuwait",
        "qatari":       "qatar",
        "bahraini":     "bahrain",
        "omani":        "oman",
        "yemeni":       "yemen",
        "nepali":       "nepal",
        "burmese":      "myanmar",
        "vietnamese":   "vietnam",
        "ukrainian":    "ukraine",
        "polish":       "poland",
        "swedish":      "sweden",
        "norwegian":    "norway",
        "danish":       "denmark",
        "finnish":      "finland",
        "swiss":        "switzerland",
        "austrian":     "austria",
        "belgian":      "belgium",
        "portuguese":   "portugal",
        "greek":        "greece",
        "romanian":     "romania",
        "peruvian":     "peru",
        "colombian":    "colombia",
        "venezuelan":   "venezuela",
        "chilean":      "chile",
        "argentinian":  "argentina",
        "cuban":        "cuba",
        "jamaican":     "jamaica",
        "sudanese":     "sudan",
        "somali":       "somalia",
        "libyan":       "libya",
        "congolese":    "democratic republic of the congo",
        "ugandan":      "uganda",
        "zimbabwean":   "zimbabwe",
        "zambian":      "zambia",
        "tanzanian":    "tanzania",
        "kazakh":       "kazakhstan",
        "uzbek":        "uzbekistan",
        "slovak":       "slovakia",
        "croatian":     "croatia",
        "serbian":      "serbia",
        "bulgarian":    "bulgaria",
        "albanian":     "albania",
        "czech":        "czech republic",
        "hungarian":    "hungary",

        # Country names as people actually type them (the database stores the
        # official long name for some of these, so the alias has to point at
        # the stored spelling or the country would never be found).
        "usa":              "united states of america",
        "u.s.":             "united states of america",
        "u.s.a.":           "united states of america",
        "america":          "united states of america",
        "united states":    "united states of america",
        "uk":               "united kingdom",
        "u.k.":             "united kingdom",
        "britain":          "united kingdom",
        "great britain":    "united kingdom",
        "england":          "united kingdom",
        "scotland":         "united kingdom",
        "wales":            "united kingdom",
        "northern ireland": "united kingdom",
        "uae":              "united arab emirates",
        "emirates":         "united arab emirates",
        "holland":          "netherlands",
        "china":            "people's republic of china",
        "south korea":      "republic of korea",
        "korea":            "republic of korea",
        "north korea":      "democratic people's republic of korea",
        "congo":            "democratic republic of the congo",
        "drc":              "democratic republic of the congo",
        "burma":            "myanmar",
        "czechia":          "czech republic",
        "ivory coast":      "cote d'ivoire",

        # City to country mappings
        "dubai":        "united arab emirates",
        "abu dhabi":    "united arab emirates",
        "sharjah":      "united arab emirates",
        "karachi":      "pakistan",
        "lahore":       "pakistan",
        "islamabad":    "pakistan",
        "mumbai":       "india",
        "delhi":        "india",
        "bangalore":    "india",
        "dhaka":        "bangladesh",
        "kabul":        "afghanistan",
        "riyadh":       "saudi arabia",
        "jeddah":       "saudi arabia",
        "doha":         "qatar",
        "manama":       "bahrain",
        "muscat":       "oman",
        "sanaa":        "yemen",
        "amman":        "jordan",
        "beirut":       "lebanon",
        "damascus":     "syria",
        "baghdad":      "iraq",
        "tehran":       "iran",
        "cairo":        "egypt",
        "casablanca":   "morocco",
        "nairobi":      "kenya",
        "lagos":        "nigeria",
        "accra":        "ghana",
        "addis ababa":  "ethiopia",
        "johannesburg": "south africa",
        "cape town":    "south africa",
        "kinshasa":     "democratic republic of the congo",
        "kampala":      "uganda",
        "harare":       "zimbabwe",
        "lusaka":       "zambia",
        "dar es salaam":"tanzania",
        "khartoum":     "sudan",
        "mogadishu":    "somalia",
        "tripoli":      "libya",
        "tunis":        "tunisia",
        "algiers":      "algeria",
        "kathmandu":    "nepal",
        "colombo":      "sri lanka",
        "yangon":       "myanmar",
        "hanoi":        "vietnam",
        "bangkok":      "thailand",
        "jakarta":      "indonesia",
        "kuala lumpur": "malaysia",
        "manila":       "philippines",
        "beijing":      "people's republic of china",
        "shanghai":     "people's republic of china",
        "tokyo":        "japan",
        "seoul":        "republic of korea",
        "moscow":       "russia",
        "kyiv":         "ukraine",
        "warsaw":       "poland",
        "prague":       "czech republic",
        "budapest":     "hungary",
        "bucharest":    "romania",
        "sofia":        "bulgaria",
        "athens":       "greece",
        "lisbon":       "portugal",
        "madrid":       "spain",
        "rome":         "italy",
        "paris":        "france",
        "berlin":       "germany",
        "amsterdam":    "netherlands",
        "brussels":     "belgium",
        "vienna":       "austria",
        "zurich":       "switzerland",
        "stockholm":    "sweden",
        "oslo":         "norway",
        "copenhagen":   "denmark",
        "helsinki":     "finland",
        "london":       "united kingdom",
        "toronto":      "canada",
        "vancouver":    "canada",
        "sydney":       "australia",
        "melbourne":    "australia",
        "mexico city":  "mexico",
        "sao paulo":    "brazil",
        "rio":          "brazil",
        "buenos aires": "argentina",
        "bogota":       "colombia",
        "lima":         "peru",
        "havana":       "cuba",
        "kingston":     "jamaica",
    }

    # Point every alias at the EXACT spelling the table uses, so the substring
    # test below can never miss on case or accents (Côte d'Ivoire, Réunion).
    by_folded = {_fold(r['country']): r['country'] for r in all_countries}
    alias_map = {}
    for alias, target in name_map.items():
        alias_map[_fold(alias)] = by_folded.get(_fold(target), target)

    # Normalize input - replace known names/adjectives. One single pass,
    # longest alias first, and only on whole words: "abu dhabi" beats "dhabi",
    # and "thai" is no longer replaced inside "thailand" (which used to turn
    # the country into "thailandland" and lose it completely).
    text = " " + _fold(user_input) + " "
    pattern = re.compile("|".join(
        r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        for alias in sorted(alias_map, key=len, reverse=True)))
    text = pattern.sub(
        lambda m: " " + _fold(alias_map[m.group(0)]) + " ", text)
    text = re.sub(r"\s+", " ", text)

    # Score every country in DB against normalized input
    best_country = None
    best_score = 0

    for row in all_countries:
        country_name = _fold(row['country'])
        country_code = (row['country_code'] or '').lower()
        names = {country_name}
        if country_name.startswith("the "):    # "The Bahamas", "The Gambia"
            names.add(country_name[4:])
        score = 0

        # Full country name found in text
        if any(n in text for n in names):
            # Longer name = stronger match. The word count keeps multi-word
            # names strong; the character count breaks the ties that let
            # "Niger" come out level with "Nigeria" on the word "nigeria".
            score += len(country_name.split()) * 3 + len(country_name)

        # Country code found as standalone word. Skipped for codes that are
        # ordinary English words, so "call in an emergency" cannot answer with
        # India and "tell me" cannot answer with Montenegro.
        if (country_code and country_code not in COMMON_WORD_CODES
                and country_code in text.split()):
            score += 2

        if score > best_score:
            best_score = score
            best_country = row['country']

    if not best_country:
        db.close()
        return None

    # Fetch full row for winning country
    cur.execute(
        "SELECT * FROM emergency_numbers WHERE country = ?",
        (best_country,)
    )
    result = cur.fetchone()
    db.close()
    return dict(result) if result else None

# ── ROUTE DETECTOR ───────────────────────────────
BODY_WORDS = [
    "hurt","pain","bleed","burn","broke","broken",
    "breathing","breathe","unconscious","waking",
    "seizure","stroke","chok","drown","swell","sting",
    "bite","shock","numb","dizzy","chest","arm","leg",
    "head","back","neck","eye","stomach","heart",
    "baby","child","pregnant","allergic","reaction",
    "trapped","fell","fall","cut","wound","blood",
    # Deliberate-injury words. Without these "someone was stabbed with a
    # knife" scored zero on every route and was answered with the off-topic
    # refusal, even though the database now has a row for it.
    "stab","stabbed","stabbing","knife","shot","gunshot","gun",
    "bullet","firearm","injur","acid","crush","crushed",
    # Electrical / disaster wording. "my brother was struck by lightning"
    # scored zero on every route and was answered with the off-topic refusal
    # even though the Lightning strike row exists.
    "lightning","electrocuted","electrocution","electrified","struck",
    "earthquake","flood","tsunami","tornado","cyclone","hurricane",
    "wildfire","landslide","avalanche","collapse","debris","smoke",
    "suffocat","evacuat"
]
MEDICINE_WORDS = [
    "tablet","pill","medicine","medication","drug",
    "swallowed","overdose","antidote","dose","took",
    "paracetamol","ibuprofen","aspirin","insulin",
    "warfarin","diazepam","antibiotic","bleach",
    "poison","chemical","syrup","injection"
]
NUMBER_WORDS = [
    "number","call","ambulance","police","fire",
    "rescue","helpline","emergency number","who to call",
    "what number","contact","helpline","brigade","emergency"
]
OFF_TOPIC_SAFE_WORDS = BODY_WORDS + MEDICINE_WORDS + NUMBER_WORDS

def detect_route(user_input):
    text = user_input.lower()
    body_score = sum(1 for w in BODY_WORDS if w in text)
    med_score  = sum(1 for w in MEDICINE_WORDS if w in text)
    num_score  = sum(1 for w in NUMBER_WORDS if w in text)
    if body_score == 0 and med_score == 0 and num_score == 0:
        return "general"
    scores = {
        "body_symptoms":     body_score,
        "medicines":         med_score,
        "emergency_numbers": num_score
    }
    return max(scores, key=scores.get)

# ── LLM CALL ─────────────────────────────────────
def ask_llm(system_prompt, user_prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 400}
        }, timeout=30)
        return r.json()["response"]
    except:
        return "ERROR: Could not reach Ollama. Run: ollama run qwen2.5:0.5b"

# ── BUILD PROMPTS ─────────────────────────────────
def get_system_prompt(severity):
    if severity == "CRITICAL":
        return ("You are an offline emergency assistant. "
                "A life is at risk RIGHT NOW. "
                "Start with EMERGENCY - ACT NOW. "
                "Give ONLY immediate numbered steps. "
                "Simple short sentences. No theory. No disclaimers.")
    elif severity == "URGENT":
        return ("You are an offline emergency assistant. "
                "This needs prompt attention. "
                "Give clear numbered steps. Keep language simple.")
    elif severity == "MODERATE":
        return ("You are an offline emergency assistant. "
                "Give clear numbered first aid steps. "
                "End with signs that would make this more serious.")
    else:
        return ("You are an offline emergency assistant. "
                "Only help with emergencies, first aid, "
                "natural disasters, and emergency numbers. "
                "Refuse anything else politely.")

def build_prompt(user_input, route, db_result):
    if route == "body_symptoms" and db_result:
        return f"""User message: {user_input}

VERIFIED EMERGENCY DATA — use this exactly:
Condition: {db_result.get('condition','')}
Severity: {db_result.get('severity','')}
Immediate action: {db_result.get('immediate_action','')}
What NOT to do: {db_result.get('what_not_to_do','')}

Format as numbered steps."""

    elif route == "medicines" and db_result:
        return f"""User message: {user_input}

VERIFIED MEDICINE DATA — use this exactly:
Medicine: {db_result.get('medicine_name','')}
Also known as: {db_result.get('aliases','')}
Overdose symptoms: {db_result.get('overdose_symptoms','')}
Overdose action: {db_result.get('overdose_action','')}
Antidote: {db_result.get('antidote','')}
Warnings: {db_result.get('warnings','')}

Format overdose action as numbered steps."""

    elif route == "emergency_numbers" and db_result:
        other = db_result.get('other','{}')
        return f"""User message: {user_input}

VERIFIED EMERGENCY NUMBERS — use exactly these, never guess:
Country: {db_result.get('country','')}
Police: {db_result.get('police','')}
Ambulance: {db_result.get('ambulance','')}
Fire: {db_result.get('fire','')}
Other: {other}

Tell the user exactly which number to call."""

    else:
        return user_input

# ── BANNER ───────────────────────────────────────
BANNERS = {
    "CRITICAL": "🔴 CRITICAL EMERGENCY — ACT NOW",
    "URGENT":   "🟡 URGENT — NEEDS ATTENTION SOON",
    "MODERATE": "🟢 MODERATE — MANAGEABLE SITUATION",
    "UNKNOWN":  "ℹ️  GENERAL ASSISTANCE"
}

# ── MAIN CHAT ────────────────────────────────────
def chat(user_input):
    route = detect_route(user_input)

    # Hard refusal for off-topic
    safe = any(w in user_input.lower() for w in OFF_TOPIC_SAFE_WORDS)
    if route == "general" and not safe:
        print("\nℹ️  GENERAL ASSISTANCE")
        print("─" * 40)
        print("I am an offline emergency assistant.")
        print("I can only help with medical emergencies,")
        print("first aid, natural disasters, and")
        print("emergency contact numbers.")
        print(f"\n[SOURCE: hardcoded_refusal]")
        return

    # Query correct DB
    db_result = None
    severity = "UNKNOWN"

    if route == "body_symptoms":
        db_result = query_body_symptoms(user_input)
        if db_result:
            severity = db_result.get('severity', 'URGENT')

    elif route == "medicines":
        db_result = query_medicine(user_input)
        if db_result:
            severity = "CRITICAL"

    elif route == "emergency_numbers":
        db_result = query_emergency_numbers(user_input)
        severity = "URGENT"

    # Build and send to LLM
    system = get_system_prompt(severity)
    prompt = build_prompt(user_input, route, db_result)
    response = ask_llm(system, prompt)

    # Print result
    banner = BANNERS.get(severity, BANNERS["UNKNOWN"])
    source = "db+llm" if db_result else "llm_only"
    matched = ""
    if db_result:
        matched = (db_result.get('condition') or
                   db_result.get('medicine_name') or
                   db_result.get('country',''))

    print(f"\n{banner}")
    print("─" * 40)
    print(response)
    print(f"\n[ROUTE: {route} | SOURCE: {source}"
          + (f" | MATCHED: {matched}" if matched else "")
          + "]")

# ── INTERACTIVE LOOP ─────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*40)
    print("  IVYAGO — Offline Emergency Assistant")
    print("  Type your emergency. Type 'quit' to exit.")
    print("="*40)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except KeyboardInterrupt:
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ["quit","exit","q"]:
            print("Exiting.")
            break

        chat(user_input)