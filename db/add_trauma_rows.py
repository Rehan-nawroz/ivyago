import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "body_symptoms.db")

# (body_part, symptoms, condition, severity, immediate_action,
#  what_not_to_do, keywords)
NEW_ROWS = [
    (
        "arm, chest, abdomen, leg",
        "bullet wound, gunshot wound, severe bleeding, penetrating injury, "
        "shooting pain, shot in arm, shot in leg, shot in chest",
        "Gunshot Wound",
        "CRITICAL",
        "Call emergency services immediately. Apply firm direct pressure to "
        "the wound with a clean cloth. Do NOT remove the cloth even if it "
        "soaks through. If on a limb and bleeding is uncontrollable apply a "
        "tourniquet 2 to 3 inches above the wound and note the time it was "
        "applied. Keep the person still and lying down. Do not give food or "
        "water. Keep them warm with a blanket. Talk to them calmly until help "
        "arrives.",
        "Do not remove the bullet or any object from the wound. Do not remove "
        "the cloth once applied even if soaked through. Do not let the person "
        "walk or stand. Do not give water or food. Do not leave them alone.",
        "bullet, gunshot, shot, shooting, gun wound, bullet wound, arm shot, "
        "leg shot, chest shot, badly injured bullet, penetrating wound, "
        "shot by gun, gun injury, firearm, fired at, gun shot, bullet in arm, "
        "bullet in leg, bullet in chest, bullet in shoulder, bullet in stomach, "
        "shot in the stomach, shot in the shoulder, shot in the back, "
        "injured by a bullet, hit by a bullet, gunshot to the arm, "
        "gunshot to the leg",
    ),
    (
        "chest, abdomen, back, arm, leg, neck",
        "stab wound, knife wound, deep puncture, bleeding heavily, blade still "
        "in the wound, sharp-object injury",
        "Stab / knife wound",
        "CRITICAL",
        "Call emergency services immediately. Press firmly on the wound with a "
        "clean cloth or dressing and keep pressing without lifting it to look. "
        "If the knife or object is still in the wound, leave it in place and "
        "press around it, padding on both sides. If the wound is on an arm or "
        "leg and bleeding will not stop, apply a tourniquet 2 to 3 inches above "
        "the wound and write down the time it was applied. Lay the person down, "
        "keep them warm and still. Do not give food or water. Watch their "
        "breathing and be ready to start CPR.",
        "Do not pull out a knife or any object stuck in the wound. Do not "
        "remove the cloth once it is applied, even if it soaks through - add "
        "more on top. Do not let the person walk, eat or drink. Do not poke "
        "around inside the wound. Do not leave them alone.",
        "stabbed, stab, stab wound, stabbing, knife, knife wound, knifed, "
        "blade, puncture wound, punctured, stabbed in arm, stabbed in leg, "
        "stabbed in chest, stabbed in stomach, stabbed in back, "
        "stabbed in neck, sharp object wound, slashed, machete wound, "
        "someone was stabbed, got stabbed",
    ),
    (
        "face, eyes, skin, mouth, throat, hands, chest",
        "acid thrown on skin, chemical burn on face, burning skin, blistering, "
        "severe pain, damaged eyes, breathing difficulty from fumes",
        "Acid attack (acid or corrosive thrown at someone)",
        "CRITICAL",
        "Call emergency services and say it is a chemical burn. Protect "
        "yourself first - do not touch the chemical or the wet clothing. Brush "
        "off any dry powder, then flush the skin with large amounts of clean "
        "cool water for at least 20 minutes, letting the water run away from "
        "the eyes and from unaffected skin. Remove contaminated clothing while "
        "flushing. If acid is in the eyes, hold the eyelid open and flush with "
        "clean water for at least 20 minutes, and keep flushing until help "
        "arrives. Cover the burn loosely with a clean dressing. Keep the person "
        "warm and treat for shock - lay them down, raise the legs, do not give "
        "food or drink.",
        "Do not try to neutralise the chemical with baking soda, milk, oil or "
        "vinegar - that makes it worse. Do not apply ointment, toothpaste or "
        "creams. Do not burst blisters. Do not let the person rub their eyes. "
        "Do not stop flushing to wait for the ambulance. Do not give food or "
        "drink.",
        "acid attack, acid thrown, acid thrown on face, acid on face, "
        "acid in eyes, acid burn, acid splash, acid on skin, acid on hand, "
        "corrosive on skin, corrosive thrown, chemical burn face, "
        "chemical burn on face, chemical attack, chemical assault, "
        "thrown acid, face burned by chemical, lye thrown, drain cleaner "
        "thrown, burning from acid, vitriol attack",
    ),
]

# condition -> extra keywords that must be present for a user to reach the row
EXTRA_KEYWORDS = {
    "Near-drowning": [
        "drowned", "nearly drowned", "near drowned", "fell in water",
        "fell into water", "fell in the water", "cant swim", "can not swim",
        "cannot swim", "swallowed water", "went under the water",
        "went under water", "kept under water", "drowning in water",
        "drowning in pool", "drowned in pool", "rescued from the water",
        "pulled from a pool", "sinking under water",
    ],
    "Lightning strike": [
        "electrocuted by lightning", "hit by lightning", "struck by lightning",
        "struck by lightening", "lightning strike victim", "lightening strike",
        "thunder struck", "thunderstruck", "lightning hit",
        "person struck by lightning",
    ],
    "Crush injury trapped under rubble": [
        "crushed", "crushed by", "crushed under", "crushed my leg",
        "trapped under car", "trapped under a car", "trapped under vehicle",
        "car on my leg", "car on top of me", "heavy object on body",
        "heavy object on chest", "heavy object on me", "heavy weight on body",
        "pinned under debris", "trapped under machine", "trapped under lift",
        "industrial crush", "wall fell on me", "fell on my leg",
    ],
}


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

        enriched = []
        already = []
        for condition, extras in EXTRA_KEYWORDS.items():
            row = con.execute(
                "SELECT id, keywords FROM body_symptoms WHERE condition = ?",
                (condition,)).fetchone()
            if row is None:
                print("WARNING: no row for %r - skipped" % condition)
                continue
            row_id, keywords = row
            existing = [k.strip().lower() for k in (keywords or "").split(",")]
            missing = [k for k in extras if k.lower() not in existing]
            if not missing:
                already.append(condition)
                continue
            merged = ", ".join(
                [k.strip() for k in (keywords or "").split(",") if k.strip()]
                + missing)
            con.execute("UPDATE body_symptoms SET keywords = ? WHERE id = ?",
                        (merged, row_id))
            enriched.append("%s (+%d keywords)" % (condition, len(missing)))

        con.commit()
        after = con.execute("SELECT COUNT(*) FROM body_symptoms").fetchone()[0]
        crit = con.execute(
            "SELECT COUNT(*) FROM body_symptoms WHERE severity='CRITICAL'"
        ).fetchone()[0]
    finally:
        con.close()

    print("rows before: %d" % before)
    print("rows after : %d" % after)
    print("CRITICAL   : %d" % crit)
    print("inserted (%d):" % len(added))
    for c in added:
        print("  + %s" % c)
    if skipped:
        print("already present (%d): %s" % (len(skipped), "; ".join(skipped)))
    print("keywords enriched (%d):" % len(enriched))
    for e in enriched:
        print("  ~ %s" % e)
    if already:
        print("keywords already complete (%d): %s"
              % (len(already), "; ".join(already)))


if __name__ == "__main__":
    main()
