"""
generate_dummy_data.py
----------------------
Creates DUMMY raw data shaped like what the HUD contextual inquiry collects,
for 8 analysed participants (2 per counterbalancing group). It includes the
mistakes real data has, so every cleaning step has something to do:

  raw/screening_demographics.csv   form export: messy IDs, a duplicate, text in
                                   number fields, 2 people who fail screening
  raw/participant_roster.csv       PRIVATE: real names -> participant codes
                                   (used only to anonymise transcripts)
  raw/session_log.csv              researcher log: messy game/HUD labels,
                                   a dropout (P03) and a wrong HUD preset (P06);
                                   P09 and P10 replace them
  raw/gameplay_tags.csv            event tags as exported by the coding app
                                   (coder A all sessions, coder B ~25 %)
  raw/gameplay_exclusions.csv      segments coders marked to skip
                                   (static, no gameplay, corrupted)
  raw/transcripts/*.txt            raw interview transcripts with fillers,
                                   silences, names and gamer tags
  raw/interview_codes.csv          coded statements as exported by the app
                                   (P01 left uncoded for practice)
  raw/sa_responses.csv + sa_answer_key.csv
  raw/gaze/<P>_S<n>.csv            raw webcam gaze samples (10 Hz) with blinks,
                                   low-confidence and off-screen points
  raw/aoi_regions.csv              screen regions of each HUD element

Replace raw/ with your real exports later; the other scripts never call this one.

Run:  python scripts/generate_dummy_data.py
"""
from pathlib import Path
import random

import numpy as np
import pandas as pd

SEED = 2026
rng = np.random.default_rng(SEED)
random.seed(SEED)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
(RAW / "transcripts").mkdir(parents=True, exist_ok=True)
(RAW / "gaze").mkdir(parents=True, exist_ok=True)

GROUPS = {
    1: [("GTA V", "minimal"), ("Cyberpunk 2077", "full")],
    2: [("GTA V", "full"), ("Cyberpunk 2077", "minimal")],
    3: [("Cyberpunk 2077", "minimal"), ("GTA V", "full")],
    4: [("Cyberpunk 2077", "full"), ("GTA V", "minimal")],
}
SESSION_S = 30 * 60
N_ASSIGNED = 10
REPLACES = {9: 6, 10: 3}            # P09 replaces P06, P10 replaces P03
DROPOUT, DEVIATION = 3, 6


def group_of(pid):
    return GROUPS_OF.get(pid)


GROUPS_OF = {p: (p - 1) % 4 + 1 for p in range(1, 9)}
GROUPS_OF.update({9: GROUPS_OF[6], 10: GROUPS_OF[3]})

FIRST = ["Miguel", "Andrea", "Paolo", "Bea", "Carlo", "Janelle", "Marco", "Trisha", "Rafael", "Nicole"]
LAST = ["Santos", "Reyes", "Cruz", "Bautista", "Garcia", "Mendoza", "Torres", "Ramos", "Flores", "Villanueva"]
TAGS = ["xXnightowlXx", "kuyaGamer21", "beabyte", "carlo.exe", "jnl_plays", "marcopolo99", "trishzz",
        "raf_aim", "nicnic", "pao_ow"]
GENRES = ["Open-world", "FPS", "Action-adventure", "RPG"]

# ---------------------------------------------------------------------------
# 1. Screening/demographics + private roster
# ---------------------------------------------------------------------------
roster, demo = [], []
expertise_of = {}
for i in range(1, N_ASSIGNED + 1):
    pid = f"P{i:02d}"
    exp = int(rng.integers(1, 6))
    expertise_of[i] = exp
    roster.append({"participant": pid, "full_name": f"{FIRST[i-1]} {LAST[i-1]}", "gamer_tag": TAGS[i-1]})
    demo.append({"Timestamp": f"2026-11-{12 + i % 6} 1{i % 8}:0{i % 6}:00", "Participant Code": pid,
                 "Age": int(rng.integers(18, 25)), "Primary gaming genre": GENRES[i % 4],
                 "Average weekly hours of play": str(int(np.clip(rng.normal(3 + 3 * exp, 3), 1, 35))),
                 "Self-rated gaming expertise (1-5)": exp,
                 "History of motion sickness in 3D games?": "No", "I agree to the consent form": "Yes"})
demo[0]["Participant Code"] = "p1"
demo[1]["Participant Code"] = "P 02"
demo[3]["Primary gaming genre"] = "open world"
demo[4]["Average weekly hours of play"] = "10+ hrs"
demo[6]["Average weekly hours of play"] = ""
demo.append({**demo[2], "Participant Code": "S01", "Age": 17})
demo.append({**demo[2], "Participant Code": "S02", "History of motion sickness in 3D games?": "Yes"})
demo.append(dict(demo[5]))
pd.DataFrame(demo).to_csv(RAW / "screening_demographics.csv", index=False)
pd.DataFrame(roster).to_csv(RAW / "participant_roster.csv", index=False)

# ---------------------------------------------------------------------------
# 2. Session log
# ---------------------------------------------------------------------------
G_SPELL = {"GTA V": ["GTA V", "GTA5", "gta v"], "Cyberpunk 2077": ["Cyberpunk 2077", "Cyberpunk", "CP2077"]}
H_SPELL = {"full": ["Full", "full HUD"], "minimal": ["Minimal", "minimal HUD", "min"]}
plan, log = {}, []
for i in range(1, N_ASSIGNED + 1):
    pid = f"P{i:02d}"
    for s, (game, hud) in enumerate(GROUPS[GROUPS_OF[i]], start=1):
        if i == DROPOUT and s == 2:
            continue
        actual_hud = "minimal" if (i == DEVIATION and s == 1) else hud
        plan[(pid, s)] = (game, actual_hud)
        start = pd.Timestamp(f"2026-11-20 {12 + s}:{(i * 5) % 60:02d}:00")
        log.append({"participant": pid if i != 5 else "P005", "group": GROUPS_OF[i], "session": s,
                    "game": random.choice(G_SPELL[game]), "hud_condition": random.choice(H_SPELL[actual_hud]),
                    "start_time": start.strftime("%H:%M:%S"),
                    "end_time": (start + pd.Timedelta(seconds=SESSION_S)).strftime("%H:%M:%S"),
                    "notes": "Researcher applied wrong HUD preset" if (i == DEVIATION and s == 1)
                    else ("Participant left after session 1" if (i == DROPOUT) else "")})
pd.DataFrame(log).to_csv(RAW / "session_log.csv", index=False)

# ---------------------------------------------------------------------------
# 3. Gameplay tags + exclusion segments (as exported by the coding app)
# ---------------------------------------------------------------------------
CATEGORY = {"full_map_open": "Navigation", "navigation_error": "Navigation",
            "objective_received": "Mission", "objective_reached": "Mission",
            "hesitation": "HUD comprehension", "missed_prompt": "HUD comprehension",
            "unintended_action": "HUD comprehension", "menu_break": "Immersion"}
BASE = {"full_map_open": 0.10, "navigation_error": 0.08, "hesitation": 0.20,
        "missed_prompt": 0.05, "unintended_action": 0.06, "menu_break": 0.07}
HUD_X = {"full_map_open": 3.0, "navigation_error": 2.3, "hesitation": 1.8,
         "missed_prompt": 1.3, "unintended_action": 1.0, "menu_break": 0.75}
GAME_X = {"GTA V": 1.0, "Cyberpunk 2077": 1.2}
NOTES = {"full_map_open": ["paused to check full map", "opened map, zoomed in on objective"],
         "navigation_error": ["missed the turn, U-turned", "drove past objective street"],
         "hesitation": ["stopped and looked around", "stood still at intersection"],
         "missed_prompt": ["walked past talk prompt", "did not notice pick-up prompt"],
         "unintended_action": ["opened weapon wheel by accident", "jumped instead of entering car"],
         "menu_break": ["opened inventory mid-mission", "checked phone menu"],
         "objective_received": ["new objective shown"], "objective_reached": ["objective complete"]}
DOUBLE = {("P04", 1), ("P04", 2), ("P08", 1), ("P08", 2)}

tags, excl = [], []
for (pid, s), (game, hud) in plan.items():
    i = int(pid[1:])
    skill = 1.25 - 0.1 * expertise_of[i]
    # segments to skip
    segs = []
    t = rng.uniform(120, 300)
    for _ in range(int(rng.integers(1, 3))):
        a = t + rng.uniform(100, 400)
        b = a + rng.uniform(60, 180)
        if b < SESSION_S - 60:
            segs.append((a, b, "static"))
        t = b
    a = rng.uniform(700, 900)
    segs.append((a, a + rng.uniform(20, 60), "no_gameplay"))
    if (pid, s) == ("P07", 2):
        segs.append((1300.0, 1390.0, "corrupted"))
    if (pid, s) == ("P02", 2):
        segs.append((300.0, 1500.0, "corrupted"))   # most of the session unusable
    for a, b, why in segs:
        excl.append({"participant": pid, "session": s, "start_s": round(a, 1), "end_s": round(b, 1),
                     "reason": why, "coder": "A"})

    def in_skip(x):
        return any(a <= x <= b for a, b, _ in segs)

    rows = []
    for ev, base in BASE.items():
        lam = base * (HUD_X[ev] if hud == "minimal" else 1) * GAME_X[game] * skill
        if hud == "minimal" and ev != "menu_break":
            lam *= 1 - 0.08 * (expertise_of[i] - 3)
        for x in rng.uniform(5, SESSION_S - 5, rng.poisson(lam * SESSION_S / 60)):
            if in_skip(x) and rng.random() < 0.9:
                continue
            rows.append((x, ev))
    tt = 40.0
    for k in range(4):
        tto = max(45, rng.normal(150 * (1.5 if hud == "minimal" else 1) * GAME_X[game] * skill, 35))
        rows.append((tt, "objective_received"))
        if tt + tto < SESSION_S:
            rows.append((tt + tto, "objective_reached"))
        tt += tto + rng.uniform(120, 260)
        if tt > SESSION_S - 120:
            break
    for x, ev in rows:
        tags.append({"participant": pid, "session": s, "t_s": round(x, 1), "event": ev, "category": CATEGORY[ev],
                     "note": random.choice(NOTES[ev]), "coder": "A"})
        if (pid, s) in DOUBLE and rng.random() < 0.88:
            tags.append({"participant": pid, "session": s, "t_s": round(float(np.clip(x + rng.normal(0, 2.5), 0, SESSION_S)), 1),
                         "event": ev, "category": CATEGORY[ev], "note": "", "coder": "B"})
    if (pid, s) in DOUBLE:
        for x in rng.uniform(5, SESSION_S - 5, rng.poisson(1.5)):
            ev = random.choice(list(BASE))
            tags.append({"participant": pid, "session": s, "t_s": round(x, 1), "event": ev, "category": CATEGORY[ev],
                         "note": "", "coder": "B"})
tags.append(dict(tags[12]))                                                       # duplicate row
tags.append({"participant": "P05", "session": 2, "t_s": 1910.0, "event": "hesitation",
             "category": "HUD comprehension", "note": "", "coder": "A"})          # after session end
pd.DataFrame(tags).to_csv(RAW / "gameplay_tags.csv", index=False)
pd.DataFrame(excl).to_csv(RAW / "gameplay_exclusions.csv", index=False)

# ---------------------------------------------------------------------------
# 4. Raw interview transcripts (+ what the codes would be)
# ---------------------------------------------------------------------------
QUESTIONS = {
    1: "How did you figure out where to go during the session? What did you look at or rely on?",
    2: "Were there moments when something on the screen confused you? What was happening?",
    3: "Which HUD elements, if any, pulled your attention away from what you were doing?",
    4: "Was there any HUD element that didn't work the way you expected?",
    5: "How aware were you of the passing of time while playing?",
    6: "Was there a point where you had to stop to figure out what the game was telling you?",
    7: "What information, if any, did you feel was missing from the screen?",
    8: "What would you change about the HUD you just used, and why?",
    9: "Was there a moment in either session where you felt completely absorbed? What was on screen?",
    10: "Comparing both sessions, which HUD setup gave you the better experience exploring, and why?",
    11: "In which session was it easier to understand what was happening and what to do next?",
    12: "If you could design your own HUD, which elements would you keep and which would you remove?",
}
# phrase bank: (code, theme, text), split by HUD condition
BANK = {
    "full": {
        1: [("relied on mini-map", "Navigation reliance", "I mostly just followed the line on the minimap"),
            ("followed waypoint marker", "Navigation reliance", "I kept looking at the waypoint marker and drove toward it")],
        2: [("no confusion", "Learning curve", "not really, everything was pretty clear"),
            ("cluttered screen", "HUD distraction", "at first there was too much stuff on the screen at once")],
        3: [("eyes on mini-map corner", "HUD distraction", "my eyes kept going to the minimap corner instead of the road"),
            ("notifications pulled focus", "HUD distraction", "the pop-up notifications pulled my focus away")],
        4: [("worked as expected", "Learning curve", "no, it all worked like I expected"),
            ("marker unclear indoors", "Information gaps", "the marker got confusing when I was inside a building")],
        5: [("aware of time", "Absorption", "I was kind of aware of the time, I kept checking the objective"),
            ("time passed quickly", "Absorption", "honestly time went by fast")],
        6: [("did not need to stop", "Navigation reliance", "no, I never really had to stop, the map told me everything")],
        7: [("nothing missing", "Navigation reliance", "nothing was missing, if anything there was too much")],
        8: [("remove clutter", "HUD distraction", "I would make the HUD smaller and remove some of the notifications")],
    },
    "minimal": {
        1: [("used landmarks", "Environmental attention", "I had to use landmarks like the tall buildings and signs"),
            ("guessed direction", "Disorientation", "I just kind of guessed which direction to go")],
        2: [("felt lost", "Disorientation", "yeah I got lost a lot because there was no map"),
            ("unsure of objective", "Disorientation", "I was not sure where the objective was")],
        3: [("no HUD distraction", "Environmental attention", "nothing really, I was looking at the city more"),
            ("focused on world", "Absorption", "I was focused on the world itself, the streets and the people")],
        4: [("missing objective marker", "Information gaps", "I expected a marker to show up but it never did"),
            ("prompt easy to miss", "Information gaps", "the prompts were easy to miss without the other stuff")],
        5: [("lost track of time", "Absorption", "I lost track of time, it felt like I was really in the city"),
            ("time dragged when lost", "Disorientation", "it felt long when I was lost, I kept checking how long it had been")],
        6: [("stopped to figure out", "Disorientation", "yes, I had to stop many times and open the full map")],
        7: [("wanted mini-map back", "Information gaps", "I wanted the minimap back, and the objective distance")],
        8: [("add small compass", "Information gaps", "I would add a small compass so I do not get lost but keep it clean")],
    },
    "final": {
        9: [("absorbed without HUD", "Absorption", "in the session without the map, when I was just driving around at night"),
            ("absorbed in combat", "Absorption", "during the fight, I forgot about everything else")],
        10: [("prefer minimal for exploring", "Absorption", "the minimal one felt better for exploring even if I got lost"),
             ("prefer full for exploring", "Navigation reliance", "the full one because I did not waste time getting lost")],
        11: [("full easier to understand", "Navigation reliance", "the full HUD was easier to understand what to do next")],
        12: [("keep health and compass", "Information gaps", "I would keep health and a compass and remove the notifications")],
    },
}
FILLERS = ["uh,", "um,", "like,", "you know,", "uhm", "ahh,"]
codes = []
used_codes, used_participants = set(), set()
for (pid, s), (game, hud) in plan.items():
    if pid != "P01":
        used_participants.add(pid)
    i = int(pid[1:])
    name, tag = roster[i - 1]["full_name"], roster[i - 1]["gamer_tag"]
    friend = random.choice([f for f in FIRST if f != name.split()[0]])
    lines = [f"Participant: {pid} | Session {s} | {game} | {hud} HUD | Interviewer: Researcher 2",
             f"[00:00] Interviewer: Okay {name.split()[0]}, thanks. Let's start the interview for session {s}."]
    clock = 10
    blocks = [(q, BANK[hud][q]) for q in range(1, 9)]
    if s == 2 and (pid, 1) in plan:
        blocks += [(q, BANK["final"][q]) for q in range(9, 13)]
    for q, options in blocks:
        # later participants mostly repeat codes already heard (how saturation looks in practice)
        seen_opts = [o for o in options if o[0] in used_codes]
        if seen_opts and len(used_participants) >= 4:
            options = seen_opts
        code, theme, text = options[int(rng.integers(0, len(options)))]
        if pid != "P01":
            used_codes.add(code)
        lines.append(f"[{clock // 60:02d}:{clock % 60:02d}] Interviewer: Q{q}. {QUESTIONS[q]}")
        clock += int(rng.integers(4, 9))
        pre = " ".join(random.sample(FILLERS, 2))
        sil = f" [silence {int(rng.integers(3, 9))}s]" if rng.random() < 0.5 else ""
        extra = ""
        r = rng.random()
        if r < 0.15:
            extra = f" My friend {friend} told me it's the same in other games."
        elif r < 0.25:
            extra = f" I usually stream as {tag} so I play a lot."
        elif r < 0.3:
            extra = f" Like I said, I'm {name}, I play this at home."
        words = text.split()
        if len(words) > 6 and rng.random() < 0.6:   # a filler in the middle
            k = int(rng.integers(2, len(words) - 2))
            words = words[:k] + [random.choice(FILLERS)] + words[k:]
        lines.append(f"[{clock // 60:02d}:{clock % 60:02d}] {pid}: {pre}{sil} {' '.join(words)}.{extra}")
        clock += int(rng.integers(15, 40))
        if pid != "P01":
            codes.append({"participant": pid, "session": s, "question": f"Q{q}", "excerpt": text,
                          "code": code, "theme": theme, "coder": "A"})
    (RAW / "transcripts" / f"{pid}_S{s}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
codes.append({**codes[0], "code": codes[0]["code"].title() + " "})                 # inconsistent spelling
pd.DataFrame(codes).to_csv(RAW / "interview_codes.csv", index=False)

# ---------------------------------------------------------------------------
# 5. Situation awareness questions
# ---------------------------------------------------------------------------
SA_Q = [("Q1", "Perception", ["Full", "More than half", "Less than half", "Almost none"]),
        ("Q2", "Perception", ["Yes", "No"]),
        ("Q3", "Comprehension", ["Ahead", "Behind", "Left", "Right"]),
        ("Q4", "Comprehension", ["Very close", "Medium", "Far"]),
        ("Q5", "Projection", ["Continue straight", "Turn at next intersection", "Turn around", "Find a vehicle"]),
        ("Q6", "Projection", ["Under 1 minute", "1-3 minutes", "Over 3 minutes"])]
P_OK = {("Perception", "full"): .86, ("Perception", "minimal"): .80, ("Comprehension", "full"): .82,
        ("Comprehension", "minimal"): .52, ("Projection", "full"): .74, ("Projection", "minimal"): .50}
sa, key = [], []
for (pid, s), (game, hud) in plan.items():
    for qid, level, opts in SA_Q:
        correct = random.choice(opts)
        key.append({"participant": pid, "session": s, "question": qid, "correct_answer": correct})
        p = P_OK[(level, hud)] + 0.03 * (expertise_of[int(pid[1:])] - 3)
        r = rng.random()
        ans = correct if r < p else ("I don't know" if r < p + .08 else random.choice([o for o in opts if o != correct]))
        if rng.random() < .15:
            ans = ans.lower() + " "
        sa.append({"participant": pid, "session": s, "question": qid, "level": level, "answer": ans})
sa[3]["answer"] = ""
pd.DataFrame(sa).to_csv(RAW / "sa_responses.csv", index=False)
pd.DataFrame(key).to_csv(RAW / "sa_answer_key.csv", index=False)

# ---------------------------------------------------------------------------
# 6. AOI regions + raw gaze samples
# ---------------------------------------------------------------------------
# Normalised screen coordinates (0-1, origin top-left). Measure these from a
# screenshot of each game's real HUD before running the study.
AOI = [
    ("GTA V", "full", "Mini-map", .015, .74, .20, .95),
    ("GTA V", "full", "Status bars", .015, .95, .20, .985),
    ("GTA V", "full", "Objective text", .30, .86, .70, .94),
    ("GTA V", "minimal", "Status bars", .015, .95, .20, .985),
    ("Cyberpunk 2077", "full", "Mini-map", .84, .04, .975, .26),
    ("Cyberpunk 2077", "full", "Quest tracker", .80, .28, .985, .42),
    ("Cyberpunk 2077", "full", "Status bars", .025, .04, .24, .10),
    ("Cyberpunk 2077", "minimal", "Status bars", .025, .04, .24, .10),
]
pd.DataFrame(AOI, columns=["game", "hud", "aoi", "x0", "y0", "x1", "y1"]).to_csv(RAW / "aoi_regions.csv", index=False)
LOOK = {"Mini-map": .13, "Quest tracker": .06, "Objective text": .05, "Status bars": .04}
HZ = 10
for (pid, s), (game, hud) in plan.items():
    n = SESSION_S * HZ
    boxes = [a for a in AOI if a[0] == game and a[1] == hud]
    probs = [LOOK[b[2]] for b in boxes]
    world = 1 - sum(probs)
    which = rng.choice(len(boxes) + 1, size=n, p=probs + [world])
    x = np.clip(rng.normal(.5, .16 if hud == "full" else .21, n), 0, 1)
    y = np.clip(rng.normal(.48, .13 if hud == "full" else .17, n), 0, 1)
    for k, b in enumerate(boxes):
        m = which == k
        x[m] = rng.uniform(b[3], b[5], m.sum())
        y[m] = rng.uniform(b[4], b[6], m.sum())
    # webcam noise
    x = x + rng.normal(0, .02, n)
    y = y + rng.normal(0, .02, n)
    conf = np.clip(rng.normal(.85, .1, n), 0, 1)
    if (pid, s) == ("P08", 2):
        conf = np.clip(rng.normal(.45, .15, n), 0, 1)   # glasses glare: mostly unusable
    blink = rng.random(n) < .03
    x[blink], y[blink] = np.nan, np.nan
    off = rng.random(n) < .015
    x[off] = rng.uniform(1.05, 1.4, off.sum())
    pd.DataFrame({"t_s": np.round(np.arange(n) / HZ, 1), "x": np.round(x, 4), "y": np.round(y, 4),
                  "confidence": np.round(conf, 3)}).to_csv(RAW / "gaze" / f"{pid}_S{s}.csv", index=False)

print("Dummy raw data written to", RAW)
print(f"  sessions: {len(plan)}  tags: {len(tags)}  exclusions: {len(excl)}  coded statements: {len(codes)}")
