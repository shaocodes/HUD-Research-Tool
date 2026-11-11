"""
app_sync.py — move data between the pipeline and the HUD Study Coding app
-------------------------------------------------------------------------
  python scripts/app_sync.py seed      build app/seed/*.json: recordings, cleaned
                                       transcripts, codebook and SAMPLE tags/codes
                                       (by = "sample") to load into the app
  python scripts/app_sync.py import <dir>
                                       read the app's database (one JSON file per
                                       document, as saved by Claude's ArtifactData
                                       tool, or exported by hand) and write
                                       raw/gameplay_tags.csv, raw/gameplay_exclusions.csv,
                                       raw/interview_codes.csv and raw/practice_tags.csv
                                       in the exact format clean.py reads.
"""
from pathlib import Path
import json
import re
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, CLEAN, SEED = ROOT / "raw", ROOT / "clean", ROOT / "app" / "seed"
CATEGORY = {"full_map_open": "Navigation", "navigation_error": "Navigation", "objective_received": "Mission",
            "objective_reached": "Mission", "hesitation": "HUD comprehension", "missed_prompt": "HUD comprehension",
            "unintended_action": "HUD comprehension", "menu_break": "Immersion"}


def seed():
    SEED.mkdir(parents=True, exist_ok=True)
    for f in SEED.glob("*.json"):
        f.unlink()
    docs = []
    docs.append(("sessions", "practice_full", {"kind": "practice", "label": "Practice clip 1 · full HUD", "hud": "full",
                                               "video": "practice_full.mp4", "duration_s": 146, "order": 0}))
    docs.append(("sessions", "practice_minimal", {"kind": "practice", "label": "Practice clip 2 · minimal HUD", "hud": "minimal",
                                                  "video": "practice_minimal.mp4", "duration_s": 148, "order": 1}))
    sess = pd.read_csv(CLEAN / "sessions.csv")
    ans = pd.read_csv(CLEAN / "interview_answers.csv")
    qtext = pd.read_csv(CLEAN / "interview_questions.csv").set_index("question")["question_text"].to_dict()
    for i, r in enumerate(sess.itertuples()):
        sid = f"{r.participant}_S{r.session}"
        a = ans[(ans["participant"] == r.participant) & (ans["session"] == r.session)]
        a = a.assign(n=a["question"].str[1:].astype(int)).sort_values("n")
        raw_path = CLEAN / "transcripts_names_removed" / f"{sid}.txt"
        docs.append(("sessions", sid, {
            "kind": "study", "participant": r.participant, "session": int(r.session), "game": r.game, "hud": r.hud,
            "group": int(r.group), "duration_s": 1800, "order": 10 + i, "video": None,
            "transcript_raw": raw_path.read_text(encoding="utf-8") if raw_path.exists() else "",
            "answers": [{"q": q, "question": qtext.get(q, ""), "answer": x} for q, x in zip(a["question"], a["answer"])]}))

    tags = pd.read_csv(RAW / "gameplay_tags.csv", keep_default_na=False)
    skips = pd.read_csv(RAW / "gameplay_exclusions.csv")
    keep = set(zip(sess["participant"], sess["session"]))
    for (p, s, c), g in tags.groupby(["participant", "session", "coder"]):
        if (p, s) not in keep:
            continue
        sk = skips[(skips["participant"] == p) & (skips["session"] == s) & (skips["coder"] == c)]
        docs.append(("tagsets", f"{p}_S{s}__{c}__sample", {
            "session_id": f"{p}_S{s}", "participant": p, "session": int(s), "clip": None, "kind": "study",
            "coder": c, "by": "sample", "updated_at": "2026-11-11T00:00:00Z",
            "tags": [{"t_s": float(t), "event": e, "note": n} for t, e, n in
                     sorted(zip(g["t_s"], g["event"], g["note"]))],
            "skips": [{"start_s": float(a), "end_s": float(b), "reason": w} for a, b, w in
                      sorted(zip(sk["start_s"], sk["end_s"], sk["reason"]))]}))
    codes = pd.read_csv(RAW / "interview_codes.csv", keep_default_na=False)
    codes["code"] = codes["code"].str.strip().str.lower()
    for (p, s, c), g in codes.groupby(["participant", "session", "coder"]):
        if (p, s) not in keep:
            continue
        docs.append(("codesets", f"{p}_S{s}__{c}__sample", {
            "session_id": f"{p}_S{s}", "participant": p, "session": int(s), "coder": c, "by": "sample",
            "updated_at": "2026-11-11T00:00:00Z",
            "items": [{"question": q, "excerpt": x, "code": k, "theme": t} for q, x, k, t in
                      zip(g["question"], g["excerpt"], g["code"], g["theme"])]}))
    book = codes.drop_duplicates("code")[["code", "theme"]].sort_values(["theme", "code"])
    docs.append(("codebook", "main", {"codes": book.to_dict(orient="records"), "updated_at": "2026-11-11T00:00:00Z"}))
    for col, did, body in docs:
        (SEED / f"{col}__{did}.json").write_text(json.dumps(body, ensure_ascii=False))
    print(f"app_sync seed: {len(docs)} documents -> {SEED}")


def load_docs(folder):
    """Accepts ArtifactData out_dir layout (<dir>/<collection>/<id>.json) or a flat folder."""
    out = {}
    for f in Path(folder).rglob("*.json"):
        body = json.loads(f.read_text(encoding="utf-8"))
        body = body.get("data", body) if isinstance(body, dict) else body
        out.setdefault(f.parent.name, []).append((f.stem, body))
    return out


def import_export(folder):
    docs = load_docs(folder)
    tags, skips, prac, codes = [], [], [], []
    for _, d in docs.get("tagsets", []):
        if d.get("kind") == "practice":
            for t in d.get("tags", []):
                prac.append({"clip": d.get("clip") or d.get("session_id"), "t_s": t["t_s"], "event": t["event"],
                             "tagged_by": f"Coder {d['coder']} ({'sample' if d.get('by') == 'sample' else 'app user ' + str(d.get('by'))[-4:]})"})
            continue
        for t in d.get("tags", []):
            tags.append({"participant": d["participant"], "session": d["session"], "t_s": t["t_s"], "event": t["event"],
                         "category": CATEGORY.get(t["event"], ""), "note": t.get("note", ""), "coder": d["coder"]})
        for k in d.get("skips", []):
            skips.append({"participant": d["participant"], "session": d["session"], "start_s": k["start_s"],
                          "end_s": k["end_s"], "reason": k["reason"], "coder": d["coder"]})
    for _, d in docs.get("codesets", []):
        for it in d.get("items", []):
            codes.append({"participant": d["participant"], "session": d["session"], "question": it["question"],
                          "excerpt": it["excerpt"], "code": it["code"], "theme": it["theme"], "coder": d["coder"]})
    pd.DataFrame(tags).to_csv(RAW / "gameplay_tags.csv", index=False)
    pd.DataFrame(skips).to_csv(RAW / "gameplay_exclusions.csv", index=False)
    pd.DataFrame(codes).to_csv(RAW / "interview_codes.csv", index=False)
    if prac:
        pd.DataFrame(prac).to_csv(RAW / "practice_tags.csv", index=False)
    print(f"app_sync import: {len(tags)} tags, {len(skips)} skipped segments, {len(codes)} codes, {len(prac)} practice tags -> raw/")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "seed":
        seed()
    elif len(sys.argv) >= 3 and sys.argv[1] == "import":
        import_export(sys.argv[2])
    else:
        print(__doc__)
