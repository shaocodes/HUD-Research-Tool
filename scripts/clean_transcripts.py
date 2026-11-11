"""
clean_transcripts.py — step 2: interview transcripts
----------------------------------------------------
Input : raw/transcripts/<P>_S<n>.txt   (after speech-to-text, one line per turn:
                                        "[mm:ss] Speaker: text")
        raw/participant_roster.csv     (PRIVATE: real names and gamer tags)
        clean/sessions.csv             (from clean.py: which sessions are kept)

For every answer it
  1. removes silence markers like "[silence 5s]"
  2. removes filler words: uh, um, uhm, ahh, er, and "like," / "you know,"
     only when used as fillers (followed by a comma), so "like the buildings" stays
  3. anonymises: full names -> [participant], other first/last names -> [name],
     gamer tags -> [username]; also in the interviewer's lines
  4. splits the transcript into answers by question number (Q1..Q12)

Outputs
  clean/transcripts/<P>_S<n>.txt   cleaned, anonymised transcript (safe to share)
  clean/interview_table.csv        one row per participant x session, one column per question
  clean/interview_answers.csv      the same in long form (participant, session, question, answer)
  clean/transcript_cleaning_log.csv  what was removed per transcript
Also checks that every coded excerpt (clean/interview_codes.csv) is still found
in the cleaned answer it belongs to.

Run:  python scripts/clean_transcripts.py
"""
from pathlib import Path
import re

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, CLEAN = ROOT / "raw", ROOT / "clean"
(CLEAN / "transcripts").mkdir(parents=True, exist_ok=True)

FILLER_WORDS = r"(?:uh+|um+|uhm+|ahh*|ahm+|er+|hmm+)"
FILLER_PHRASES = r"(?:like|you know|i mean|kinda like)"
LINE = re.compile(r"^\[(\d{2}:\d{2})\]\s*([^:]+):\s*(.*)$")
QNUM = re.compile(r"\bQ(\d{1,2})\.")

roster = pd.read_csv(RAW / "participant_roster.csv")
sessions = pd.read_csv(CLEAN / "sessions.csv")
keep = set(zip(sessions["participant"], sessions["session"]))

# replacement patterns, longest first so full names go before first names
full_names = {n: "[participant]" for n in roster["full_name"]}
part_names = {}
for n in roster["full_name"]:
    for piece in n.split():
        part_names[piece] = "[name]"
tags = {t: "[username]" for t in roster["gamer_tag"]}
REPLACE = sorted({**part_names, **full_names, **tags}.items(), key=lambda kv: -len(kv[0]))


def anonymise(text, counter):
    for raw, token in REPLACE:
        pattern = re.compile(r"(?<![\w.])" + re.escape(raw) + r"(?![\w])", re.IGNORECASE)
        text, n = pattern.subn(token, text)
        counter["names_replaced"] += n
    return text


def clean_answer(text, counter):
    sil = re.findall(r"\[silence (\d+)s\]", text)
    counter["silence_s"] += sum(int(s) for s in sil)
    text = re.sub(r"\[silence \d+s\]", " ", text)
    text, n1 = re.subn(rf"(?i)\b{FILLER_WORDS}\b,?", " ", text)
    text, n2 = re.subn(rf"(?i)\b{FILLER_PHRASES},", " ", text)
    counter["fillers_removed"] += n1 + n2
    text = anonymise(text, counter)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    text = re.sub(r"\s+([.,?!])", r"\1", text)
    return text[:1].upper() + text[1:] if text else text


answers, logrows, questions = [], [], {}
for path in sorted((RAW / "transcripts").glob("*.txt")):
    m = re.match(r"(P\d+)_S(\d+)", path.stem)
    pid, s = m.group(1), int(m.group(2))
    if (pid, s) not in keep:
        logrows.append({"transcript": path.name, "fillers_removed": 0, "silence_s": 0, "names_replaced": 0,
                        "kept": False, "note": "session excluded in clean.py"})
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    counter = {"fillers_removed": 0, "silence_s": 0, "names_replaced": 0}
    # names removed but fillers kept: shows the cleaning step without exposing anyone
    scratch = {"names_replaced": 0}
    (CLEAN / "transcripts_names_removed").mkdir(exist_ok=True)
    (CLEAN / "transcripts_names_removed" / path.name).write_text(
        "\n".join(anonymise(x, scratch) for x in lines) + "\n", encoding="utf-8")
    header = anonymise(lines[0], counter)
    out, q = [header], None
    for line in lines[1:]:
        mm = LINE.match(line)
        if not mm:
            continue
        stamp, speaker, text = mm.groups()
        if speaker.strip().lower() == "interviewer":
            text = anonymise(text, counter)
            qm = QNUM.search(text)
            if qm:
                q = f"Q{int(qm.group(1))}"
                questions[q] = text[qm.end():].strip()
            out.append(f"[{stamp}] Interviewer: {text}")
        else:
            cleaned = clean_answer(text, counter)
            out.append(f"[{stamp}] {pid}: {cleaned}")
            if q:
                answers.append({"participant": pid, "session": s, "question": q, "answer": cleaned})
    (CLEAN / "transcripts" / path.name).write_text("\n".join(out) + "\n", encoding="utf-8")
    logrows.append({"transcript": path.name, **counter, "kept": True, "note": ""})

ans = pd.DataFrame(answers).merge(sessions[["participant", "session", "game", "hud"]], on=["participant", "session"])
pd.Series(questions, name="question_text").rename_axis("question").to_csv(CLEAN / "interview_questions.csv")
ans.to_csv(CLEAN / "interview_answers.csv", index=False)
qorder = [f"Q{i}" for i in range(1, 13)]
table = (ans.pivot_table(index=["participant", "session", "game", "hud"], columns="question", values="answer", aggfunc=" ".join)
         .reindex(columns=[q for q in qorder if q in set(ans["question"])]).reset_index())
table.to_csv(CLEAN / "interview_table.csv", index=False)
tlog = pd.DataFrame(logrows)
tlog.to_csv(CLEAN / "transcript_cleaning_log.csv", index=False)

# do the coded excerpts still match the cleaned text?
codes_path = CLEAN / "interview_codes.csv"
if codes_path.exists():
    codes = pd.read_csv(codes_path)
    lookup = {(r.participant, r.session, r.question): r.answer.lower() for r in ans.itertuples()}
    found = [str(x).lower().strip() in lookup.get((p, s, q), "") for p, s, q, x in
             zip(codes["participant"], codes["session"], codes["question"], codes["excerpt"])]
    codes["excerpt_found"] = found
    codes.to_csv(codes_path, index=False)
    missing = len(codes) - sum(found)
    print(f"  coded excerpts found in cleaned answers: {sum(found)}/{len(codes)}"
          + (f"  ({missing} to re-check)" if missing else ""))

kept = tlog[tlog["kept"]]
print(f"clean_transcripts.py: {len(kept)} transcripts cleaned, {int(kept['fillers_removed'].sum())} fillers, "
      f"{int(kept['silence_s'].sum())} s of silence markers and {int(kept['names_replaced'].sum())} names removed; "
      f"{len(table)} rows in interview_table.csv")
