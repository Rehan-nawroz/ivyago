"""Adds the benign rows a generic symptom needs so the ranking has something
safe to choose instead of a life-threatening row that merely shares the word.

Audit (done before writing this file) of the generic symptom list from the
handoff doc - dizzy, fever, vomiting, weakness, stomach pain, rash, swollen,
sore throat, headache:

  * headache   - Migraine (id 2) and Torticollis (id 43) exist, but there is
                 no plain "tension / general headache" row at all, so a bare
                 "i have a headache" had no benign row to win with. Added here.
  * weakness   - no benign row exists: every candidate for "i feel very weak"
                 was CRITICAL (Cardiogenic shock, Stroke, Acute nerve injury).
                 Added here.
  * dizzy      - Bradycardia / Hyperventilation (URGENT) already exist.
  * fever      - Ear infection (MODERATE) and several URGENT infection rows
                 already exist.
  * vomiting   - Gastroenteritis (MODERATE) and Food poisoning (MODERATE)
                 already exist.
  * stomach    - Peptic ulcer (URGENT) already exists.
  * rash       - Allergic contact rash / urticaria (MODERATE) exists.
  * sore throat- Swollen neck glands (MODERATE) exists.

So only the two rows above are inserted. Idempotent: a row is skipped when a
row with the same condition already exists, so re-running is safe.

Run with:  python db/add_benign_rows.py
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "body_symptoms.db")

# (body_part, symptoms, condition, severity, immediate_action,
#  what_not_to_do, keywords)
NEW_ROWS = [
    (
        "head",
        "dull steady ache on both sides of the head, tight band around the "
        "head, tight neck and shoulders, worse with stress, screens or a "
        "missed meal",
        "Tension / general headache",
        "MODERATE",
        "1) Rest in a quiet, dim room and drink a glass of water. 2) Take "
        "paracetamol or ibuprofen at the dose printed on the label if the "
        "person has no allergy to it and no condition that rules it out. "
        "3) Loosen tight clothing and gently massage the neck and shoulders. "
        "4) Eat something if a meal was missed and get regular sleep. Most "
        "tension headaches ease within a few hours.",
        "Do not give aspirin to a child or teenager. Do not take pain "
        "relievers for more than a few days in a row without medical advice. "
        "Do not ignore a headache that is sudden and severe (the worst ever), "
        "comes with a stiff neck, fever, confusion, weakness, slurred speech "
        "or vision loss, or follows a head injury - get emergency help.",
        "headache, head ache, head hurts, my head hurts, mild headache, "
        "slight headache, tension headache, general headache, dull headache, "
        "stress headache, everyday headache, headache on both sides, "
        "headache and tired, headache after screen, normal headache",
    ),
    (
        "whole body",
        "feeling weak or drained, low energy, tiredness after illness or "
        "poor sleep, no strength for usual tasks, heaviness in the limbs",
        "Weakness / fatigue (mild)",
        "MODERATE",
        "1) Sit or lie down and rest. 2) Drink water and eat something - low "
        "energy is often dehydration or a missed meal. 3) Sleep properly and "
        "avoid heavy activity until strength returns. 4) See a doctor if the "
        "weakness is sudden, affects one side of the body, or comes with "
        "chest pain, breathlessness, fainting, confusion or a fever that "
        "will not settle.",
        "Do not push through sudden severe weakness. Do not drive or climb "
        "if you feel faint. Do not ignore weakness in the face, arm or leg "
        "on one side, or difficulty speaking - that needs emergency help.",
        "weak, weakness, feeling weak, very weak, feel weak, fatigue, tired, "
        "no energy, low energy, exhausted, general weakness, "
        "weakness in body, whole body weakness",
    ),
]


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        before = con.execute("SELECT COUNT(*) FROM body_symptoms").fetchone()[0]
        added, skipped = [], []
        for row in NEW_ROWS:
            condition = row[2]
            exists = con.execute(
                "SELECT id FROM body_symptoms WHERE condition = ?", (condition,)
            ).fetchone()
            if exists:
                skipped.append(condition)
                continue
            con.execute(
                "INSERT INTO body_symptoms "
                "(body_part, symptoms, condition, severity, immediate_action, "
                " what_not_to_do, keywords) VALUES (?, ?, ?, ?, ?, ?, ?)", row)
            added.append(condition)
        con.commit()
        after = con.execute("SELECT COUNT(*) FROM body_symptoms").fetchone()[0]
        crit = con.execute(
            "SELECT COUNT(*) FROM body_symptoms WHERE severity='CRITICAL'"
        ).fetchone()[0]
        print("inserted rows:")
        for condition in added:
            rec = con.execute(
                "SELECT id, condition, severity FROM body_symptoms "
                "WHERE condition = ?", (condition,)).fetchone()
            print("  + id %s | %s | %s" % (rec[0], rec[1], rec[2]))
    finally:
        con.close()

    print("rows before: %d" % before)
    print("rows after : %d" % after)
    print("CRITICAL   : %d" % crit)
    if skipped:
        print("already present (%d): %s" % (len(skipped), "; ".join(skipped)))


if __name__ == "__main__":
    main()
