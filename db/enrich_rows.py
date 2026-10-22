import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BS_PATH = os.path.join(BASE_DIR, "body_symptoms.db")
MED_PATH = os.path.join(BASE_DIR, "medicines.db")

# condition (LIKE pattern) -> keywords to append
BODY_KEYWORD_ADDITIONS = {
    "Near-drowning": [
        "underwater", "car underwater", "submerged", "sank underwater",
        "pulled out of water", "in the water", "sinking",
    ],
    "Seizure": [
        "swallowed tongue", "biting tongue", "during a fit", "having a fit",
        "fit", "shaking fit", "cant speak after",
    ],
    "Prolapsed umbilical cord": [
        "cord came out", "cord is out", "cord hanging out", "umbilical cord out",
        "waters broke", "cord first", "cord before baby",
    ],
    "Stroke (arm weakness)": [
        "cant speak", "cant talk", "cannot speak", "arm is weak", "weak arm",
        "arm went weak", "one side weak",
    ],
    "Ear infection (otitis media)": [
        "pus from ear", "pus coming from ear", "pus in ear", "ear is leaking",
        "discharge from ear", "fluid from ear",
    ],
    "Alcohol poisoning": [
        "drank alcohol", "a lot of alcohol", "lots of alcohol",
        "confused after drinking", "confused drunk",
    ],
    "Spinal fracture": [
        "bent back", "back is bent", "fell from a ladder", "ladder fall",
        "fall from height", "fell from height",
    ],
    "Ankle sprain": [
        "my ankle is swollen", "ankle is swollen", "twisted my ankle",
        "swollen ankle after twisting",
    ],
}

# The plain "Stroke" row (id 154) needs the same speech wording.
BODY_KEYWORD_ADDITIONS_BY_EXACT = {
    "Stroke": ["cant speak", "cant talk", "cannot speak", "arm is weak"],
}

# medicine_name -> aliases to append
MEDICINE_ALIAS_ADDITIONS = {
    "Zolpidem": ["sleeping pill", "sleeping tablet", "sleeping pills",
                 "sleeping tablets", "zolpidem tartrate"],
    "Zopiclone": ["sleeping pill", "sleeping tablet", "sleeping pills",
                  "sleeping tablets"],
    "Melatonin": ["sleeping pill", "sleeping tablet", "sleep aid"],
    # Common oral blood-pressure medicines, so "my child ate my blood pressure
    # tablets" stops answering with a completely unrelated tablet.
    "Amlodipine": ["blood pressure tablet", "blood pressure medicine"],
    "Losartan": ["blood pressure tablet", "blood pressure medicine"],
    "Atenolol": ["blood pressure tablet", "blood pressure medicine"],
    "Lisinopril": ["blood pressure tablet", "blood pressure medicine"],
    "Ramipril": ["blood pressure tablet", "blood pressure medicine"],
    "Metoprolol": ["blood pressure tablet", "blood pressure medicine"],
    "Nifedipine": ["blood pressure tablet", "blood pressure medicine"],
    "Hydrochlorothiazide": ["blood pressure tablet", "blood pressure medicine"],
}


def _add_csv(existing, additions):
    """Append the entries of `additions` missing (case-insensitive) from the
    comma-separated `existing` string. Returns (new_value, added_list)."""
    parts = [p.strip() for p in (existing or "").split(",") if p.strip()]
    have = {p.lower() for p in parts}
    added = []
    for item in additions:
        if item.lower() not in have:
            parts.append(item)
            have.add(item.lower())
            added.append(item)
    return ", ".join(parts), added


def main():
    changes = 0

    con = sqlite3.connect(BS_PATH)
    try:
        for pattern, extras in BODY_KEYWORD_ADDITIONS.items():
            rows = con.execute(
                "SELECT id, condition, keywords FROM body_symptoms "
                "WHERE condition LIKE ?", ("%" + pattern + "%",)).fetchall()
            for row_id, condition, keywords in rows:
                new_kw, added = _add_csv(keywords, extras)
                if added:
                    con.execute(
                        "UPDATE body_symptoms SET keywords = ? WHERE id = ?",
                        (new_kw, row_id))
                    changes += 1
                    print("BS  +%d  %-45s %s" % (row_id, condition, added))
        for condition, extras in BODY_KEYWORD_ADDITIONS_BY_EXACT.items():
            rows = con.execute(
                "SELECT id, condition, keywords FROM body_symptoms "
                "WHERE condition = ?", (condition,)).fetchall()
            for row_id, cond, keywords in rows:
                new_kw, added = _add_csv(keywords, extras)
                if added:
                    con.execute(
                        "UPDATE body_symptoms SET keywords = ? WHERE id = ?",
                        (new_kw, row_id))
                    changes += 1
                    print("BS  +%d  %-45s %s" % (row_id, cond, added))
        con.commit()
        rows = con.execute("SELECT COUNT(*) FROM body_symptoms").fetchone()[0]
    finally:
        con.close()

    con = sqlite3.connect(MED_PATH)
    try:
        for name, extras in MEDICINE_ALIAS_ADDITIONS.items():
            row = con.execute(
                "SELECT id, aliases FROM medicines WHERE medicine_name = ?",
                (name,)).fetchone()
            if not row:
                print("MED !! missing medicine: %s" % name)
                continue
            new_al, added = _add_csv(row[1], extras)
            if added:
                con.execute("UPDATE medicines SET aliases = ? WHERE id = ?",
                            (new_al, row[0]))
                changes += 1
                print("MED +%d  %-22s %s" % (row[0], name, added))
        con.commit()
        meds = con.execute("SELECT COUNT(*) FROM medicines").fetchone()[0]
    finally:
        con.close()

    print("\nbody_symptoms rows: %d" % rows)
    print("medicines rows   : %d" % meds)
    print("updates applied  : %d" % changes)


if __name__ == "__main__":
    main()
