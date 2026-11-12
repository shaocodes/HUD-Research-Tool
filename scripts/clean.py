"""
clean.py — step 1 of the pipeline: forms, sessions, gameplay, SA answers
------------------------------------------------------------------------
  1. Demographics  - normalise participant codes, drop duplicate submissions,
                     apply screening, parse weekly hours.
  2. Sessions      - normalise game/HUD labels, check every session against the
                     counterbalancing table, exclude dropouts and deviations.
  3. Gameplay      - merge the skip segments coders marked (static stretches,
                     no gameplay, corrupted footage) and compute ACTIVE play time;
                     drop duplicate tags, tags after the session ended and tags
                     inside skipped segments; flag sessions with < 50 % usable
                     footage; event rates per minute of active play; time to
                     objective from objective_received -> objective_reached.
  4. SA questions  - score against the answer key from the recordings.
  5. Interview codes (from the coding app) - merge spelling variants.

Every fix is written to clean/cleaning_log.csv.
Run:  python scripts/clean.py      (or python scripts/run_all.py)
"""
from pathlib import Path
import re

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, CLEAN = ROOT / "raw", ROOT / "clean"
CLEAN.mkdir(exist_ok=True)

SESSION_LENGTH_S = 30 * 60
MIN_USABLE_SHARE = 0.50      # sessions with less usable footage are left out of gameplay measures
EXPERT_CUTOFF = 4            # self-rated 4-5 = more experienced
PRIMARY_CODER = "A"

DESIGN = {
    1: [("Cyberpunk 2077", "full"), ("GTA V", "minimal")],
    2: [("GTA V", "minimal"), ("Cyberpunk 2077", "full")],
    3: [("Cyberpunk 2077", "minimal"), ("GTA V", "full")],
    4: [("GTA V", "full"), ("Cyberpunk 2077", "minimal")],
}
RATE_EVENTS = ["full_map_open", "navigation_error", "hesitation", "missed_prompt",
               "unintended_action", "menu_break"]

_log = []


def log(step, item, issue, action):
    _log.append({"step": step, "item": item, "issue": issue, "action": action})


def norm_pid(raw):
    s = str(raw).strip().upper().replace(" ", "")
    m = re.fullmatch(r"([PS])0*(\d+)", s)
    return f"{m.group(1)}{int(m.group(2)):02d}" if m else s


def norm_game(raw):
    s = str(raw).lower()
    return "GTA V" if "gta" in s else ("Cyberpunk 2077" if ("cyber" in s or "cp2077" in s) else np.nan)


def norm_hud(raw):
    s = str(raw).strip().lower()
    return "full" if s.startswith("full") else ("minimal" if s.startswith("min") else np.nan)


# ---------------------------------------------------------------- 1. demographics
demo = pd.read_csv(RAW / "screening_demographics.csv", dtype=str, keep_default_na=False).rename(columns={
    "Participant Code": "participant", "Age": "age", "Primary gaming genre": "genre",
    "Average weekly hours of play": "hours_raw", "Self-rated gaming expertise (1-5)": "expertise",
    "History of motion sickness in 3D games?": "motion_sickness", "I agree to the consent form": "consent"})
for old in demo["participant"]:
    if norm_pid(old) != old:
        log("demographics", norm_pid(old), f"participant code written as '{old}'", "normalised")
demo["participant"] = demo["participant"].map(norm_pid)
for pid in demo.loc[demo.duplicated("participant"), "participant"]:
    log("demographics", pid, "duplicate form submission", "kept the first one")
demo = demo.drop_duplicates("participant").copy()
demo["age"] = pd.to_numeric(demo["age"])
demo["expertise"] = pd.to_numeric(demo["expertise"])
fail = (demo["age"] < 18) | demo["motion_sickness"].str.lower().eq("yes") | demo["consent"].str.lower().ne("yes")
for _, r in demo[fail].iterrows():
    why = "under 18" if r["age"] < 18 else ("history of motion sickness" if r["motion_sickness"].lower() == "yes" else "no consent")
    log("screening", r["participant"], why, "screened out, never assigned")
demo = demo[~fail].copy()
demo["genre"] = demo["genre"].str.strip().str.lower().map(
    {"open-world": "Open-world", "open world": "Open-world", "fps": "FPS", "action-adventure": "Action-adventure",
     "rpg": "RPG"}).fillna("Other")


def hours(raw, pid):
    nums = re.findall(r"\d+", str(raw))
    if not nums:
        log("demographics", pid, "weekly hours left blank", "kept participant, hours missing")
        return np.nan
    if not str(raw).strip().isdigit():
        log("demographics", pid, f"weekly hours written as '{raw}'", f"read as {nums[0]}")
    return float(nums[0])


demo["hours_per_week"] = [hours(h, p) for h, p in zip(demo["hours_raw"], demo["participant"])]
demo["expertise_group"] = np.where(demo["expertise"] >= EXPERT_CUTOFF, "More experienced", "Less experienced")
demo = demo[["participant", "age", "genre", "hours_per_week", "expertise", "expertise_group"]]

# ---------------------------------------------------------------- 2. sessions
sess = pd.read_csv(RAW / "session_log.csv", dtype=str, keep_default_na=False)
sess["participant"] = sess["participant"].map(norm_pid)
sess[["group", "session"]] = sess[["group", "session"]].astype(int)
sess["game"] = sess["game"].map(norm_game)
sess["hud"] = sess["hud_condition"].map(norm_hud)
excluded = {}
for pid, g in sess.groupby("participant"):
    if len(g) < 2:
        excluded[pid] = "completed only one session"
        continue
    for _, r in g.iterrows():
        want = DESIGN[r["group"]][r["session"] - 1]
        if (r["game"], r["hud"]) != want:
            excluded[pid] = f"session {r['session']} played as {r['game']} {r['hud']} HUD, assigned {want[0]} {want[1]} HUD"
for pid, why in excluded.items():
    log("session check", pid, why, "participant excluded and replaced")
sess = sess[~sess["participant"].isin(excluded)].copy()
included = set(sess["participant"])
sess = sess.merge(demo, on="participant", how="left")
sess["duration_s"] = SESSION_LENGTH_S

# ---------------------------------------------------------------- 3. gameplay
tags = pd.read_csv(RAW / "gameplay_tags.csv", keep_default_na=False)
tags["participant"] = tags["participant"].map(norm_pid)
skips = pd.read_csv(RAW / "gameplay_exclusions.csv")
skips["participant"] = skips["participant"].map(norm_pid)
skips = skips[skips["participant"].isin(included) & (skips["coder"] == PRIMARY_CODER)]


def merged_segments(df):
    """Union of overlapping skip segments, clipped to the session."""
    segs = sorted((max(0, a), min(SESSION_LENGTH_S, b)) for a, b in zip(df["start_s"], df["end_s"]))
    out = []
    for a, b in segs:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


active = []
seg_of = {}
for (pid, s), g in sess.groupby(["participant", "session"]):
    sg = skips[(skips["participant"] == pid) & (skips["session"] == s)]
    segs = merged_segments(sg)
    seg_of[(pid, s)] = segs
    skipped = sum(b - a for a, b in segs)
    by_reason = sg.assign(len=sg["end_s"] - sg["start_s"]).groupby("reason")["len"].sum().to_dict()
    act = SESSION_LENGTH_S - skipped
    usable = act / SESSION_LENGTH_S >= MIN_USABLE_SHARE
    if not usable:
        log("gameplay", f"{pid} S{s}", f"only {act / 60:.1f} of 30 min usable ({', '.join(f'{k} {v/60:.0f} min' for k, v in by_reason.items())})",
            "left out of gameplay measures; interview and SA answers kept")
    active.append({"participant": pid, "session": s, "active_min": act / 60,
                   "skipped_static_min": by_reason.get("static", 0) / 60,
                   "skipped_no_gameplay_min": by_reason.get("no_gameplay", 0) / 60,
                   "skipped_corrupted_min": by_reason.get("corrupted", 0) / 60,
                   "gameplay_usable": usable})
active = pd.DataFrame(active)
log("gameplay", "all sessions", f"{active['skipped_static_min'].sum():.0f} min static, "
    f"{active['skipped_no_gameplay_min'].sum():.0f} min no gameplay, {active['skipped_corrupted_min'].sum():.0f} min corrupted",
    "subtracted from session time; rates use active minutes")

tags = tags[tags["participant"].isin(included)]
n0 = len(tags)
tags = tags.drop_duplicates(["participant", "session", "t_s", "event", "coder"])
if n0 > len(tags):
    log("gameplay", "tags", f"{n0 - len(tags)} duplicated tag(s)", "removed")
late = tags["t_s"] > SESSION_LENGTH_S
for _, r in tags[late].iterrows():
    log("gameplay", f"{r['participant']} S{r['session']}", f"tag at {r['t_s']:.0f} s is after the session ended", "removed")
tags = tags[~late]
inside = np.array([any(a <= t <= b for a, b in seg_of.get((p, s), [])) for p, s, t in
                   zip(tags["participant"], tags["session"], tags["t_s"])], dtype=bool)
if inside.any():
    log("gameplay", "tags", f"{inside.sum()} tag(s) fall inside skipped segments", "removed")
tags = tags[~inside].merge(sess[["participant", "session", "game", "hud"]], on=["participant", "session"])
tags_a = tags[tags["coder"] == PRIMARY_CODER]
tags_b = tags[tags["coder"] != PRIMARY_CODER]

counts = (tags_a[tags_a["event"].isin(RATE_EVENTS)].groupby(["participant", "session", "event"]).size()
          .unstack(fill_value=0).reindex(columns=RATE_EVENTS, fill_value=0).reset_index())


def objective_times(g):
    g = g.sort_values("t_s")
    out, open_t = [], None
    for _, r in g.iterrows():
        if r["event"] == "objective_received":
            if open_t is not None:
                out.append((open_t, np.nan))
            open_t = r["t_s"]
        elif r["event"] == "objective_reached" and open_t is not None:
            out.append((open_t, r["t_s"] - open_t))
            open_t = None
    if open_t is not None:
        out.append((open_t, np.nan))
    return out


obj_rows = []
for (pid, s), g in tags_a[tags_a["event"].str.startswith("objective")].groupby(["participant", "session"]):
    for rec, tto in objective_times(g):
        obj_rows.append({"participant": pid, "session": s, "received_s": rec, "time_to_objective_s": tto})
obj = pd.DataFrame(obj_rows)
n_open = obj["time_to_objective_s"].isna().sum()
if n_open:
    log("gameplay", "objectives", f"{n_open} objective(s) never reached before the session ended",
        "left out of mean time to objective, counted in completion rate")
obj_s = obj.groupby(["participant", "session"]).agg(
    objectives_given=("received_s", "count"),
    objectives_reached=("time_to_objective_s", lambda x: x.notna().sum()),
    time_to_objective_s=("time_to_objective_s", "mean")).reset_index()

# ---------------------------------------------------------------- 4. SA answers
sa = pd.read_csv(RAW / "sa_responses.csv", dtype=str, keep_default_na=False)
key = pd.read_csv(RAW / "sa_answer_key.csv", dtype=str, keep_default_na=False)
for df in (sa, key):
    df["participant"] = df["participant"].map(norm_pid)
    df["session"] = df["session"].astype(int)
sa = sa[sa["participant"].isin(included)].merge(key, on=["participant", "session", "question"])
a = sa["answer"].str.strip().str.casefold()
n_fmt = ((sa["answer"] != sa["correct_answer"]) & (a == sa["correct_answer"].str.strip().str.casefold())).sum()
log("sa", "answers", f"{n_fmt} correct answers typed with different capitalisation or extra spaces",
    "compared ignoring case and spaces, so they count as correct")
blank = a == ""
for _, r in sa[blank].iterrows():
    log("sa", f"{r['participant']} S{r['session']} {r['question']}", "left blank", "left out of that session's score")
sa = sa[~blank].copy()
sa["dont_know"] = a[~blank].eq("i don't know").values
sa["correct"] = (a[~blank].values == sa["correct_answer"].str.strip().str.casefold().values).astype(int)
sa_s = sa.groupby(["participant", "session"]).agg(sa_accuracy=("correct", "mean"), sa_dont_know=("dont_know", "mean")).reset_index()
sa_lvl = sa.groupby(["participant", "session", "level"])["correct"].mean().unstack().rename(columns=lambda c: "sa_" + c.lower()).reset_index()

# ---------------------------------------------------------------- 5. interview codes
iv = pd.read_csv(RAW / "interview_codes.csv", keep_default_na=False)
iv["participant"] = iv["participant"].map(norm_pid)
iv["code_key"] = iv["code"].str.strip().str.lower()
canonical = iv.groupby("code_key")["code"].agg(lambda s: s.str.strip().value_counts().index[0])
fixed = iv["code_key"].map(canonical)
for old, new in set(zip(iv["code"], fixed)):
    if old != new:
        log("interview codes", "codebook", f"code written as '{old}'", f"merged into '{new}'")
iv["code"] = fixed
iv = iv[iv["participant"].isin(included)].drop(columns="code_key").merge(
    sess[["participant", "session", "game", "hud"]], on=["participant", "session"])

# ---------------------------------------------------------------- session table
m = (sess[["participant", "group", "session", "game", "hud", "age", "genre", "hours_per_week", "expertise", "expertise_group"]]
     .merge(active, on=["participant", "session"])
     .merge(counts, on=["participant", "session"], how="left").fillna({e: 0 for e in RATE_EVENTS})
     .merge(obj_s, on=["participant", "session"], how="left")
     .merge(sa_s, on=["participant", "session"], how="left").merge(sa_lvl, on=["participant", "session"], how="left"))
m["order"] = m["session"].map({1: "First", 2: "Second"})
for e in RATE_EVENTS:
    m[f"{e}_per_min"] = m[e] / m["active_min"]
m["objective_completion"] = m["objectives_reached"] / m["objectives_given"]
gp_cols = [f"{e}_per_min" for e in RATE_EVENTS] + RATE_EVENTS + ["time_to_objective_s", "objective_completion"]
m.loc[~m["gameplay_usable"], gp_cols] = np.nan

demo[demo["participant"].isin(included)].to_csv(CLEAN / "participants.csv", index=False)
sess[["participant", "group", "session", "game", "hud"]].to_csv(CLEAN / "sessions.csv", index=False)
tags_a.to_csv(CLEAN / "gameplay_events.csv", index=False)
tags_b.to_csv(CLEAN / "gameplay_events_coderB.csv", index=False)
pd.DataFrame([{"participant": p, "session": s, "start_s": a, "end_s": b} for (p, s), sg in seg_of.items() for a, b in sg]
             ).to_csv(CLEAN / "skipped_segments.csv", index=False)
obj.to_csv(CLEAN / "objectives.csv", index=False)
sa.to_csv(CLEAN / "sa_scored.csv", index=False)
iv.to_csv(CLEAN / "interview_codes.csv", index=False)
m.round(4).to_csv(CLEAN / "session_metrics.csv", index=False)
pd.DataFrame(_log).to_csv(CLEAN / "cleaning_log.csv", index=False)

print(f"clean.py: {len(included)} participants, {len(m)} sessions "
      f"({int(m['gameplay_usable'].sum())} with usable gameplay); excluded {sorted(excluded)}; {len(_log)} log entries")
