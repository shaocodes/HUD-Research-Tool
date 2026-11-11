"""
transcribe.py — step 0: interview audio -> transcript text (runs on YOUR computer)
--------------------------------------------------------------------------------
Uses Whisper (faster-whisper) offline. The audio never leaves the computer.

Setup, once:
    pip install faster-whisper
    (the first run downloads the "small" model, about 500 MB, then works offline)

Name each recording <participant>_S<session>.<ext>, e.g. P01_S1.m4a, P01_S2.mp3,
and put them in raw/audio/. Then:
    python scripts/transcribe.py                 # all files in raw/audio/
    python scripts/transcribe.py --model medium  # more accurate, slower
    python scripts/transcribe.py --language tl   # if answers are mostly Filipino

Interview habit this relies on: the interviewer starts every question with its
number, e.g. "Question three. Which HUD elements, if any, ..." The script splits
the recording at each "question <number>", removes the question as read aloud
(it knows the fixed wording from raw/interview_questions.csv), and keeps the rest
as the participant's answer.

What it writes
  raw/transcripts/P01_S1.txt            same format clean_transcripts.py reads
  raw/transcripts/transcription_review.csv
                                         things to check by ear: questions not
                                         found, unclear passages, very short answers
Silence is dropped by Whisper's voice detection, so dead air never reaches the text.
Always listen back once and fix names of games and places Whisper mishears.
"""
from pathlib import Path
import argparse
import difflib
import re

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "raw" / "audio"
OUT_DIR = ROOT / "raw" / "transcripts"
QUESTIONS_FILE = ROOT / "raw" / "interview_questions.csv"
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".webm", ".mp4", ".aac"}

WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "first": 1, "second": 2, "third": 3,
            "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
MARKER = re.compile(r"\b(?:question|q)\s*(?:number\s*)?(\d{1,2}|" + "|".join(WORD_NUM) + r")\b[.:,]?", re.IGNORECASE)
LOW_CONFIDENCE = -1.0      # Whisper avg log-probability below this -> listen again


def load_audio(path, sr=16000):
    """Decode any audio/video file to 16 kHz mono float32 with PyAV.
    Done here (not inside faster-whisper) so it works with any PyAV version."""
    import av
    import numpy as np
    chunks = []
    with av.open(str(path)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sr)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise RuntimeError("no audio found in " + str(path))
    return np.concatenate(chunks).astype("float32") / 32768.0


def mmss(t):
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def strip_question(block, question_text):
    """Remove the question as read aloud from the start of a block; return (answer, found)."""
    if not question_text:
        return block.strip(), False
    bw = words(block)
    qw = words(question_text)
    best_end, best_ratio = None, 0.0
    # try every cut point in the first (question length + 12) words; keep the best match
    for end in range(max(1, len(qw) - 6), min(len(bw), len(qw) + 12) + 1):
        r = difflib.SequenceMatcher(None, bw[:end], qw).ratio()
        if r > best_ratio:
            best_ratio, best_end = r, end
    if best_ratio < 0.6:
        return block.strip(), False
    # map the word cut back to a character position in the original text
    count, pos = 0, 0
    for m in re.finditer(r"[A-Za-z0-9']+", block):
        count += 1
        if count == best_end:
            pos = m.end()
            break
    return block[pos:].lstrip(" ?.,!:;-").strip(), True


def find_spoken_question(text, question_text, min_ratio=0.75):
    """Locate a question read aloud WITHOUT its number. Returns (start_char, end_char) or None."""
    qw = words(question_text)
    spans = [(m.start(), m.end(), m.group().lower()) for m in re.finditer(r"[A-Za-z0-9']+", text)]
    tw = [w for *_, w in spans]
    best = (0.0, None)
    for n in range(max(3, len(qw) - 2), len(qw) + 3):
        if n > len(tw):
            break
        for i in range(0, len(tw) - n + 1):
            r = difflib.SequenceMatcher(None, tw[i:i + n], qw).ratio()
            if r > best[0]:
                best = (r, (spans[i][0], spans[i + n - 1][1]))
    return best[1] if best[0] >= min_ratio else None


def split_by_question(segments, questions, expected=None):
    """segments: list of (start, end, text, avg_logprob). Returns (intro, [(q, start, answer, found)], issues)."""
    marks = []
    for i, (st, en, tx, lp) in enumerate(segments):
        for m in MARKER.finditer(tx):
            n = m.group(1).lower()
            num = int(n) if n.isdigit() else WORD_NUM[n]
            marks.append((i, m.start(), m.end(), num, st))
    intro = " ".join(s[2] for s in segments[: marks[0][0]]) if marks else " ".join(s[2] for s in segments)
    if marks:
        intro += " " + segments[marks[0][0]][2][: marks[0][1]]
    out, issues = [], []
    for k, (i, a, b, num, st) in enumerate(marks):
        if k + 1 < len(marks):
            j, a2 = marks[k + 1][0], marks[k + 1][1]
        else:
            j, a2 = len(segments) - 1, len(segments[-1][2])
        if i == j:
            block = segments[i][2][b:a2]
        else:
            block = " ".join([segments[i][2][b:]] + [s[2] for s in segments[i + 1:j]] + [segments[j][2][:a2]])
        answer, found = strip_question(block, questions.get(num, ""))
        out.append((f"Q{num}", st, answer, found))
        if not found:
            issues.append((f"Q{num}", mmss(st), "question wording not matched: check where the answer starts"))
        if len(words(answer)) < 3:
            issues.append((f"Q{num}", mmss(st), "very short or empty answer"))
    # questions read without saying their number: split them out of the previous answer
    i = 0
    while i < len(out):
        q, st, answer, found = out[i]
        seen_now = {x[0] for x in out}
        for num, qt in questions.items():
            if f"Q{num}" in seen_now or num <= int(q[1:]):
                continue
            hit = find_spoken_question(answer, qt)
            if hit:
                before, after = answer[:hit[0]], answer[hit[1]:]
                before = re.sub(r"\b(next one|next question|okay|ok|so)[.,]?\s*$", "", before.strip(), flags=re.I)
                out[i] = (q, st, before.strip(), found)
                out.insert(i + 1, (f"Q{num}", st, after.lstrip(" ?.,!:;-").strip(), True))
                issues.append((f"Q{num}", mmss(st), "number not said; found by its wording, check the split"))
                break
        i += 1
    out = [(q, st, re.sub(r"\s+", " ", a).strip(), f) for q, st, a, f in out]
    seen = [q for q, *_ in out]
    for num in (expected or questions):
        if f"Q{num}" not in seen:
            issues.append((f"Q{num}", "", "question not heard: was 'question <number>' said aloud?"))
    for st, en, tx, lp in segments:
        if lp is not None and lp < LOW_CONFIDENCE:
            issues.append(("", mmss(st), f"unclear audio: '{tx.strip()[:60]}'"))
    return intro.strip(), out, issues


def write_transcript(pid, session, intro, answers, header_extra=""):
    lines = [f"Participant: {pid} | Session {session}{header_extra} | Interviewer: (from audio)"]
    if intro:
        lines.append(f"[00:00] Interviewer: {intro}")
    qtext = load_questions()
    for q, st, answer, _ in answers:
        lines.append(f"[{mmss(st)}] Interviewer: {q}. {qtext.get(int(q[1:]), '')}")
        lines.append(f"[{mmss(st)}] {pid}: {answer}")
    (OUT_DIR / f"{pid}_S{session}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_by_time(pid, session, segments, header_extra=""):
    lines = [f"Participant: {pid} | Session {session}{header_extra} | Interviewer: (from audio)"]
    lines += [f"[{mmss(a)}] {pid}: {t.strip()}" for a, _, t, _ in segments]
    (OUT_DIR / f"{pid}_S{session}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_questions():
    if not QUESTIONS_FILE.exists():
        return {}
    q = pd.read_csv(QUESTIONS_FILE)
    return {int(str(r.question).lstrip("Qq")): r.question_text for r in q.itertuples()}


def session_header(pid, session):
    log = ROOT / "raw" / "session_log.csv"
    if not log.exists():
        return ""
    s = pd.read_csv(log, dtype=str)
    s = s[(s["participant"].str.upper().str.replace(" ", "") == pid) & (s["session"] == str(session))]
    return f" | {s.iloc[0]['game']} | {s.iloc[0]['hud_condition']} HUD" if len(s) else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", default=str(AUDIO_DIR))
    ap.add_argument("--model", default="small", help="tiny, base, small (default), medium, large-v3")
    ap.add_argument("--language", default="en", help="en (default), tl for Filipino, or 'auto'")
    ap.add_argument("--overwrite", action="store_true", help="redo files that already have a transcript")
    args = ap.parse_args()

    from faster_whisper import WhisperModel   # imported here so the helpers can be tested without it
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    if not questions:
        print("! raw/interview_questions.csv not found: answers will still be split, but question text can't be removed.")
    files = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not files:
        print(f"No audio files in {args.folder}")
        return
    print(f"Loading Whisper '{args.model}' (first time downloads it)…")
    model = WhisperModel(args.model, device="auto", compute_type="int8")
    review = []
    for f in files:
        m = re.match(r"(?i)(P\d+)[_ -]?S(\d+)", f.stem)
        if not m:
            print(f"  skip {f.name}: name it like P01_S1{f.suffix}")
            continue
        pid, session = m.group(1).upper(), int(m.group(2))
        if (OUT_DIR / f"{pid}_S{session}.txt").exists() and not args.overwrite:
            print(f"  skip {f.name}: transcript exists (use --overwrite)")
            continue
        print(f"  transcribing {f.name} …", end="", flush=True)
        segs, info = model.transcribe(load_audio(f), language=None if args.language == "auto" else args.language,
                                      vad_filter=True, vad_parameters={"min_silence_duration_ms": 700},
                                      condition_on_previous_text=False)
        segments = [(s.start, s.end, s.text, s.avg_logprob) for s in segs]
        expected = [n for n in questions if n <= 8 or session >= 2]   # Q9-Q12 are the final, after-both-sessions questions
        intro, answers, issues = split_by_question(segments, questions, expected)
        # full timeline: every sentence with its time (separate folder, not read by the pipeline)
        (OUT_DIR / "timeline").mkdir(exist_ok=True)
        (OUT_DIR / "timeline" / f"{pid}_S{session}_timeline.txt").write_text(
            "\n".join(f"[{mmss(a)}] {t.strip()}" for a, _, t, _ in segments) + "\n", encoding="utf-8")
        if not answers:
            # no "question N" anywhere: keep the whole recording as timestamped lines instead
            write_by_time(pid, session, segments, session_header(pid, session))
            issues.insert(0, ("", "", "no questions found: transcript is per sentence with times; "
                                      "add a line 'Interviewer: Q3. ...' before each answer by hand"))
        else:
            write_transcript(pid, session, intro, answers, session_header(pid, session))
        review += [{"file": f.name, "question": q, "time": t, "check": c} for q, t, c in issues]
        print(f" {len(answers)} answers, {len(issues)} things to check ({info.duration / 60:.1f} min of audio)")
    pd.DataFrame(review, columns=["file", "question", "time", "check"]).to_csv(OUT_DIR / "transcription_review.csv", index=False)
    print(f"Done. Transcripts in {OUT_DIR}. Check transcription_review.csv, then run: python scripts/run_all.py")


if __name__ == "__main__":
    main()
