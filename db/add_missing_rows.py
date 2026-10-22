import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "body_symptoms.db")

# (body_part, symptoms, condition, severity, immediate_action,
#  what_not_to_do, keywords)
NEW_ROWS = [
    (
        "environment",
        "ground shaking, building collapse, person trapped, crush injury, "
        "debris falling, aftershocks",
        "Earthquake (building collapse / trapped)",
        "CRITICAL",
        "1) Drop to your hands and knees, take cover under a sturdy table and "
        "hold on until the shaking stops. 2) If you are outdoors, move to open "
        "ground away from buildings, walls, trees and power lines. 3) If you are "
        "trapped, cover your mouth with cloth and tap on a pipe or wall so "
        "rescuers can hear you. 4) Treat bleeding with firm pressure and keep "
        "the person warm.",
        "Do not run outside while the ground is still shaking. Do not use lifts "
        "or elevators. Do not light a match or lighter - there may be a gas "
        "leak. Do not move a seriously injured person unless they are in "
        "immediate danger.",
        "earthquake, earth quake, tremor, aftershock, building collapse, "
        "trapped, under rubble, rubble, crush injury, drop cover hold on, "
        "debris, pinned",
    ),
    (
        "environment",
        "rising water, flood water, stranded by water, swept away, water in "
        "the house, drowning risk",
        "Flood / rising flood water",
        "CRITICAL",
        "1) Move to higher ground immediately - do not wait to be told. 2) If "
        "you are in a building, go to the highest floor and take water, food "
        "and a torch. 3) Signal for help from a window or roof. 4) If you must "
        "cross water, it is safer to walk on higher ground than through it.",
        "Do not walk or drive through moving water - 15 cm of moving water can "
        "knock an adult down. Do not touch electrical equipment if it is wet. "
        "Do not drink flood water. Do not swim to help someone unless you are "
        "trained and have a float.",
        "flood, flooding, flash flood, rising water, water rising, water in "
        "house, water in my house, stranded by water, swept away, levee",
    ),
    (
        "environment",
        "fire approaching, thick smoke, embers, evacuation order, wild fire "
        "in the hills",
        "Wildfire / forest fire approaching",
        "CRITICAL",
        "1) Leave early, before the fire arrives - follow the evacuation route "
        "away from the fire, not with the wind. 2) Close all windows and doors "
        "and turn off gas. 3) Cover your nose and mouth with a damp cloth and "
        "stay low under the smoke. 4) If you are trapped, go to a cleared area "
        "or a large open space and call emergency services with your location.",
        "Do not try to outrun a wildfire uphill and do not drive into smoke. Do "
        "not re-enter a burnt area - hot spots and falling trees remain. Do not "
        "leave a car in tall dry grass.",
        "wildfire, wild fire, forest fire, bushfire, fire near my house, smoke, "
        "evacuate fire, evacuation order, embers, grass fire",
    ),
    (
        "environment",
        "building on fire, smoke filled room, trapped by fire, clothes on "
        "fire, blocked exit",
        "Building fire / how to escape",
        "CRITICAL",
        "1) Get low and crawl under the smoke to the nearest exit. 2) Feel a "
        "closed door with the back of your hand before opening it - if it is "
        "hot, use another way out. 3) Leave by the stairs, never the lift. 4) "
        "If your clothes catch fire: stop, drop and roll. 5) Once outside, stay "
        "outside and call the fire service with your address.",
        "Do not open a door that feels hot. Do not go back inside for "
        "belongings or pets. Do not use an elevator. Do not break windows unless "
        "you must escape through them.",
        "building on fire, building is on fire, house on fire, house is on "
        "fire, fire escape, escape a fire, trapped in fire, smoke, on fire, "
        "fire in my house, fire alarm",
    ),
    (
        "environment",
        "roaring sound, dark sky, swirling wind, flying debris, storm shelter",
        "Tornado / severe storm",
        "URGENT",
        "1) Go to the lowest floor of a strong building, into an interior room "
        "with no windows. 2) Crouch down and cover your head and neck with your "
        "arms and a mattress or thick blanket. 3) If you are outdoors, lie flat "
        "in a ditch or low ground and cover your head. 4) Stay there until the "
        "storm has clearly passed.",
        "Do not stay in a car, mobile home or shed. Do not shelter in a "
        "building with a wide-span roof. Do not open windows to equalise "
        "pressure. Do not go outside to watch.",
        "tornado, twister, cyclone, hurricane, typhoon, severe storm, storm "
        "coming, storm shelter, flying debris, high winds",
    ),
    (
        "environment",
        "sea withdrawing from shore, loud roar from the sea, tsunami warning, "
        "wall of water",
        "Tsunami",
        "CRITICAL",
        "1) Move inland and to high ground immediately - do not wait for an "
        "official warning. 2) If you cannot reach high ground, go to the upper "
        "floor or roof of a strong concrete building. 3) Stay there until the "
        "authorities say it is safe - waves come in sets. 4) Help children, "
        "elderly and disabled people move first.",
        "Do not go to the beach or harbour to watch. Do not return after the "
        "first wave. Do not wait for a siren before moving.",
        "tsunami, tidal wave, wave coming from the sea, sea water coming, "
        "tsunami warning, sea level drop",
    ),
    (
        "environment",
        "ground moving, trees and poles tilting, rocks falling, mud flowing, "
        "rumbling sound",
        "Landslide / mudslide",
        "CRITICAL",
        "1) Move out of the path of the slide - go to the nearest high, stable "
        "ground away from the slope. 2) If escape is impossible, curl into a "
        "ball and protect your head with your arms. 3) Once clear, stay away "
        "from the slide area and report anyone missing. 4) Treat injuries the "
        "usual way - control bleeding and keep the person warm.",
        "Do not cross a slide area or walk along the bottom of a slope. Do not "
        "stay in a valley or gully. Do not re-enter the area - more slides may "
        "follow.",
        "landslide, land slide, mudslide, mud slide, avalanche, rocks falling, "
        "slope collapse, hillside collapsed, debris flow",
    ),
    (
        "environment",
        "chemical smell, gas cloud, spill on the road, burning eyes and "
        "throat, industrial accident",
        "Chemical spill / toxic gas release",
        "CRITICAL",
        "1) Move upwind and uphill, away from the spill, into fresh air. 2) "
        "Move to a high place if the chemical is heavier than air. 3) Remove "
        "contaminated clothing and put it in a sealed bag. 4) Flush skin and "
        "eyes with clean running water for 15-20 minutes. 5) Call the fire "
        "service and tell them exactly what was spilled if you know.",
        "Do not touch or walk through the spill. Do not re-enter the area. Do "
        "not eat, drink or smoke anything that was exposed. Do not try to clean "
        "up the spill yourself.",
        "chemical spill, toxic spill, hazmat, chemical leak, gas cloud, "
        "industrial accident, chemical in air, factory leak",
    ),
    (
        "environment",
        "fallen cables on the road, sparking wire, damaged pole, car touching "
        "a wire",
        "Downed / live power lines",
        "CRITICAL",
        "1) Stay at least 10 metres away and keep everyone else back. 2) Treat "
        "every wire as live, even if it looks dead. 3) If the wire is on a "
        "vehicle, tell the people inside to stay in the car and wait for help. "
        "4) Call emergency services and the electricity company and warn "
        "passers-by. 5) If someone is in contact with a wire, do not touch them "
        "until the power is off.",
        "Do not touch the wire, the pole, or anything the wire is touching. Do "
        "not drive over or park near downed lines. Do not try to move the "
        "cable with a stick.",
        "power lines, power line, downed power lines, fallen power line, live "
        "wire, electric wire down, electrocution risk, sparking wire",
    ),
    (
        "environment",
        "no trail, darkness falling, cold, exhausted, no phone signal, "
        "unfamiliar terrain",
        "Lost / stranded in the mountains or wilderness",
        "URGENT",
        "1) Stop and stay put once you realise you are lost - you are easier "
        "to find stationary. 2) Get out of the wind, keep dry and insulate "
        "yourself from the ground. 3) Make yourself visible: bright clothing, "
        "a signal mirror, whistle blasts or three fires in a triangle. 4) "
        "Conserve water and battery, and try one text or call even with no "
        "signal bars. 5) If you must move, follow water downstream but stay on "
        "high ground.",
        "Do not keep walking without marking your route. Do not push on in the "
        "dark. Do not drink untreated water unless you must. Do not abandon "
        "your shelter for a shortcut.",
        "lost in the mountains, lost in the woods, lost in the forest, lost in "
        "the jungle, lost, stranded, wilderness, mountains, hiking, survival, "
        "exposure to cold",
    ),
    (
        "whole body",
        "sudden bright flash, very loud thunder, person collapsed, burns, "
        "cardiac arrest, temporary paralysis",
        "Lightning strike",
        "CRITICAL",
        "1) Move the person to a safer place if the storm is continuing - "
        "lightning victims do not carry a charge and are safe to touch. 2) "
        "Check breathing and pulse; if they are not breathing start CPR "
        "immediately and use an AED if available. 3) Treat burns with cool "
        "water and a clean dressing. 4) Call emergency services and keep the "
        "person warm. 5) Anyone struck needs to be checked in hospital even if "
        "they seem fine.",
        "Do not shelter under a lone tree, near water or near metal fences. Do "
        "not resume outdoor activity for 30 minutes after the last thunder. Do "
        "not delay CPR while waiting for help.",
        "lightning strike, struck by lightning, lightning, thunderstorm, "
        "electric shock, thunderstruck",
    ),
    (
        "whole body",
        "person pinned under debris, heavy weight on the body, crush injury, "
        "swollen limb, no pulse in the limb, collapse victim",
        "Crush injury trapped under rubble",
        "CRITICAL",
        "1) Call for rescue and keep the casualty still and warm while you "
        "wait. 2) Control visible bleeding with firm pressure. 3) If the "
        "person has been trapped for more than 15 minutes, do NOT release the "
        "weight on your own - a doctor or rescue team must do it. 4) Keep "
        "talking to them and watch their breathing. 5) Treat for shock: lie "
        "them flat, keep warm, do not give food or drink.",
        "Do not pull the person out by force. Do not give food or drink. Do "
        "not leave them alone. Do not apply a tight bandage on a crushed limb.",
        "trapped under rubble, trapped under, crush injury, trapped, stuck "
        "under, pinned, debris, building collapse on me, compressed",
    ),
    (
        "skin",
        "red painful skin, blisters, scalded hand or arm, shiny wet burn, "
        "steam burn, hot liquid spill",
        "Scald burn from hot liquid or steam",
        "URGENT",
        "1) Move away from the heat and cool the burn under cool running water "
        "for 20 minutes - start immediately, it still helps up to 3 hours "
        "later. 2) Remove rings, watches and tight clothing before the area "
        "swells. 3) Cover the burn loosely with cling film or a clean, "
        "non-fluffy cloth. 4) Keep the rest of the person warm. 5) Give "
        "paracetamol or ibuprofen for pain and seek medical help if the burn "
        "is larger than the person's palm or on the face, hands, feet, joints "
        "or genitals, or if the person is a child or elderly.",
        "Do not apply ice, butter, toothpaste, oil or creams. Do not burst "
        "blisters. Do not use cotton wool or adhesive dressings. Do not "
        "immerse the person in cold water.",
        "boiling water, scald, scalded, hot liquid, hot water, spilled hot, "
        "spilled boiling, steam burn, hot oil, burned my arm, burnt my arm, "
        "burn on my arm, burned my hand, burnt my hand, burn on hand",
    ),
    (
        "skin",
        "puncture wounds from teeth, torn skin, bleeding bite, deep animal "
        "bite, bite that will not stop bleeding",
        "Dog bite or animal bite wound",
        "URGENT",
        "1) Control the bleeding by pressing firmly on the wound with a clean "
        "cloth. 2) Once bleeding slows, wash the wound with running water and "
        "soap for at least 15 minutes. 3) Cover it with a clean, dry dressing. "
        "4) Go to a clinic the same day: a tetanus booster and rabies "
        "vaccination may be needed. 5) Note the animal and whether it is "
        "known, and report the bite to the local authority.",
        "Do not close a deep bite wound yourself with stitches or tape. Do not "
        "delay rabies treatment. Do not apply a tourniquet unless bleeding is "
        "uncontrollable. Do not put your hand in the animal's mouth.",
        "dog bite, animal bite, bitten by a dog, dog bit me, cat bite, bite "
        "wound, rabies, deep bite, monkey bite, human bite, bitten",
    ),
    (
        "skin",
        "sting mark, redness, swelling of the limb, pain and heat, spreading "
        "swelling, allergic reaction",
        "Insect sting (bee, wasp, scorpion) with swelling",
        "URGENT",
        "1) Scrape the sting out sideways with a fingernail or card - do not "
        "squeeze it. 2) Wash the area with soap and water. 3) Apply a cold "
        "pack wrapped in cloth for 10-20 minutes. 4) Keep the limb still and "
        "raised, and give an antihistamine if available. 5) Watch closely for "
        "the next 30 minutes: swelling of the face or throat, breathing "
        "difficulty, dizziness or collapse means CALL EMERGENCY SERVICES at "
        "once - that is anaphylaxis.",
        "Do not squeeze or pull the sting. Do not scratch the area. Do not "
        "leave the person alone if they feel unwell. Do not ignore swelling "
        "that spreads quickly.",
        "bee sting, wasp sting, insect sting, insect bite, stung, sting, "
        "scorpion sting, hornet, swelling after sting, sting on arm",
    ),
    (
        "blood",
        "swallowed poison bait, rat poison, bleeding gums or nose a day later, "
        "bruising, blood in urine, anticoagulant poisoning",
        "Rodenticide (rat poison) poisoning",
        "CRITICAL",
        "1) Call emergency services or a poison centre immediately and say "
        "which poison was swallowed and how long ago. 2) Do not make the "
        "person vomit. 3) Take the poison packet, box or a photo of it to "
        "hospital. 4) The antidote is vitamin K1 and it must be given by a "
        "doctor - bleeding can start 1 to 3 days after swallowing it, so go "
        "even if the person feels completely well. 5) If there is bleeding, "
        "press on it firmly and go to hospital immediately.",
        "Do not induce vomiting. Do not wait for symptoms before seeking help. "
        "Do not give food or drink if the person is drowsy or fitting. Do not "
        "throw the poison packet away.",
        "rat poison, rodenticide, mouse poison, poisoned bait, rat bait, "
        "swallowed rat poison, ate rat poison, weed killer, anticoagulant poison",
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
    finally:
        con.close()

    print("rows before: %d" % before)
    print("rows after : %d" % after)
    print("CRITICAL   : %d" % crit)
    print("added (%d):" % len(added))
    for c in added:
        print("  + %s" % c)
    if skipped:
        print("already present (%d): %s" % (len(skipped), "; ".join(skipped)))


if __name__ == "__main__":
    main()
