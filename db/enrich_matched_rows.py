import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "body_symptoms.db")

# condition -> {"symptoms": [...], "keywords": [...]}
ENRICHMENTS = {
    "Heart attack (Myocardial Infarction)": {
        "symptoms": [
            "numbness or tingling in the left arm",
            "chest hurts",
            "pressure or tightness in the chest",
        ],
        "keywords": [
            "numb left arm",
            "left arm numb",
            "left arm numbness",
            "arm goes numb with chest pain",
            "chest hurts",
            "chest pain and numb arm",
            "chest pain spreading to the arm",
            "tight chest",
            "chest pressure",
        ],
    },
    "Subungual haematoma (nail injury)": {
        "symptoms": [
            "crushed finger in a door",
            "finger caught in a door",
            "door slammed on the finger",
            "fingertip crush",
        ],
        "keywords": [
            "finger in the door",
            "finger caught in door",
            "door slammed on finger",
            "crushed finger in door",
            "crushed fingertip",
            "finger got crushed",
            "slammed my finger",
        ],
    },
    "Deep skin laceration": {
        "symptoms": [
            "cut finger",
            "cut with a knife",
        ],
        "keywords": [
            "cut finger",
            "cut my finger",
            "finger cut",
            "sliced finger",
            "knife cut",
            "cut with a knife",
            "cut myself",
            "small cut that won't stop bleeding",
        ],
    },
}


def _merge(existing, extras):
    have = [p.strip().lower() for p in (existing or "").split(",")]
    missing = [e for e in extras if e.lower() not in have]
    if not missing:
        return None, []
    merged = ", ".join(
        [p.strip() for p in (existing or "").split(",") if p.strip()] + missing)
    return merged, missing


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        for condition, fields in ENRICHMENTS.items():
            row = con.execute(
                "SELECT id, symptoms, keywords FROM body_symptoms "
                "WHERE condition = ?", (condition,)).fetchone()
            if row is None:
                print("WARNING: row %r not found - skipped" % condition)
                continue
            row_id, symptoms, keywords = row
            new_symptoms, added_symptoms = _merge(
                symptoms, fields.get("symptoms", []))
            new_keywords, added_keywords = _merge(
                keywords, fields.get("keywords", []))
            if new_symptoms:
                con.execute("UPDATE body_symptoms SET symptoms = ? WHERE id = ?",
                            (new_symptoms, row_id))
            if new_keywords:
                con.execute("UPDATE body_symptoms SET keywords = ? WHERE id = ?",
                            (new_keywords, row_id))
            print("%s (id %d)" % (condition, row_id))
            print("  symptoms added (%d): %s"
                  % (len(added_symptoms), "; ".join(added_symptoms) or "-"))
            print("  keywords added (%d): %s"
                  % (len(added_keywords), "; ".join(added_keywords) or "-"))
        con.commit()
        total = con.execute(
            "SELECT COUNT(*) FROM body_symptoms").fetchone()[0]
    finally:
        con.close()
    print("body_symptoms rows: %d" % total)


if __name__ == "__main__":
    main()
