"""
HUD Study Studio: a local app. Everything runs on THIS computer; nothing is uploaded anywhere.

    python studio/server.py        (or double-click Start.bat)

Opens http://localhost:8765 with three tabs:
  1. Recordings   upload interview audio/video (transcribed with Whisper) and gameplay recordings
  2. Tag & code   the coding app (gameplay tagging, interview coding), saved on this computer
  3. Run & results  data checklist, one-click pipeline, figures and tables
"""
from pathlib import Path
import csv
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "studio"
RAW = ROOT / "raw"
DB = ROOT / "studio_data" / "db"
GROUP_FILE = ROOT / "studio_data" / "group.json"
SB_CONFIG = ROOT / "app-supabase" / "supabase-config.js"
PORT = int(os.environ.get("HUD_PORT", "8765"))

DESIGN = {1: [("Cyberpunk 2077", "full"), ("GTA V", "minimal")], 2: [("GTA V", "minimal"), ("Cyberpunk 2077", "full")],
          3: [("Cyberpunk 2077", "minimal"), ("GTA V", "full")], 4: [("GTA V", "full"), ("Cyberpunk 2077", "minimal")]}
CSV_SLOTS = {  # name -> (what it is, needed for)
    "session_log.csv": ("Session log (built for you from the Recordings tab)", "design check"),
    "screening_demographics.csv": ("Screening form export (Google Forms CSV)", "expertise groups"),
    "sa_responses.csv": ("HUD comprehension answers (participant, session, question, level, answer)", "comprehension scores"),
    "sa_answer_key.csv": ("Correct answers per session (participant, session, question, correct_answer)", "comprehension scores"),
    "participant_roster.csv": ("PRIVATE: real names and gamer tags, used only to remove names", "anonymising transcripts"),
    "aoi_regions.csv": ("HUD box positions per game and HUD (measure from a screenshot)", "gaze maps"),
}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".webm", ".mp4", ".aac", ".mov", ".mkv"}
LOCK = threading.Lock()
JOB = {"name": "", "running": False, "log": [], "code": None, "started": 0}


# ------------------------------------------------------------------ small helpers
def pid_ok(x):
    m = re.fullmatch(r"(?i)p?0*(\d{1,3})", str(x).strip())
    return f"P{int(m.group(1)):02d}" if m else None


def sid(p, s):
    return f"{p}_S{int(s)}"


def read_doc(col, id_):
    f = DB / col / f"{id_}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def write_doc(col, id_, body):
    (DB / col).mkdir(parents=True, exist_ok=True)
    (DB / col / f"{id_}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def list_docs(col):
    d = DB / col
    return [{"id": f.stem, "data": json.loads(f.read_text(encoding="utf-8"))} for f in sorted(d.glob("*.json"))] if d.exists() else []


def csv_rows(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def csv_write(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def ensure_practice():
    for i, (k, label, hud) in enumerate([("practice_full", "Practice clip 1 · full HUD", "full"),
                                          ("practice_minimal", "Practice clip 2 · minimal HUD", "minimal")]):
        if (ROOT / "practice" / f"{k}.mp4").exists() and not read_doc("sessions", k):
            write_doc("sessions", k, {"kind": "practice", "label": label, "hud": hud, "video": f"/practice/{k}.mp4",
                                      "duration_s": 146, "order": i})


# ------------------------------------------------------------------ transcript text -> answers
FILLER_WORDS = r"(?:uh+|um+|uhm+|ahh*|ahm+|er+|hmm+)"
FILLER_PHRASES = r"(?:like|you know|i mean|kinda like)"
LINE = re.compile(r"^\[(\d{2}:\d{2})\]\s*([^:]+):\s*(.*)$")
QNUM = re.compile(r"\bQ(\d{1,2})\.")


def anonymiser():
    rows = csv_rows(RAW / "participant_roster.csv")
    pairs = {}
    for r in rows:
        for piece in (r.get("full_name") or "").split():
            pairs[piece] = "[name]"
        if r.get("full_name"):
            pairs[r["full_name"]] = "[participant]"
        if r.get("gamer_tag"):
            pairs[r["gamer_tag"]] = "[username]"
    order = sorted(pairs.items(), key=lambda kv: -len(kv[0]))

    def run(text):
        for raw, token in order:
            text = re.sub(r"(?<![\w.])" + re.escape(raw) + r"(?![\w])", token, text, flags=re.I)
        return text
    return run


def clean_text(text, anon):
    text = re.sub(r"\[silence \d+s\]", " ", text)
    text = re.sub(rf"(?i)\b{FILLER_WORDS}\b,?", " ", text)
    text = re.sub(rf"(?i)\b{FILLER_PHRASES},", " ", text)
    text = anon(text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    text = re.sub(r"\s+([.,?!])", r"\1", text)
    return text[:1].upper() + text[1:] if text else text


def build_answers(raw_text):
    """Parse a transcript (Interviewer: Qn. lines + participant lines) into [(Qn, question, cleaned answer)] and the anonymised text."""
    anon = anonymiser()
    qtext = {r["question"]: r["question_text"] for r in csv_rows(RAW / "interview_questions.csv")}
    lines = raw_text.splitlines()
    answers, q, cur = [], None, {}
    for line in lines[1:]:
        m = LINE.match(line)
        if not m:
            continue
        stamp, speaker, text = m.groups()
        if speaker.strip().lower() == "interviewer":
            qm = QNUM.search(text)
            if qm:
                q = f"Q{int(qm.group(1))}"
                cur[q] = cur.get(q, "")
        elif q:
            cur[q] = (cur[q] + " " + text).strip()
    for q, a in cur.items():
        answers.append({"q": q, "question": qtext.get(q, ""), "answer": clean_text(a, anon)})
    answers.sort(key=lambda x: int(x["q"][1:]))
    return answers, "\n".join(anon(x) for x in lines) + "\n"


def refresh_session_from_transcript(p, s):
    f = RAW / "transcripts" / f"{sid(p, s)}.txt"
    doc = read_doc("sessions", sid(p, s))
    if not f.exists() or not doc:
        return 0
    answers, shown = build_answers(f.read_text(encoding="utf-8"))
    doc["answers"], doc["transcript_raw"] = answers, shown
    write_doc("sessions", sid(p, s), doc)
    return len(answers)


# ------------------------------------------------------------------ sessions
def register_session(p, s, game, hud, group, **fields):
    key = sid(p, s)
    doc = read_doc("sessions", key) or {"kind": "study", "participant": p, "session": int(s), "duration_s": 1800,
                                        "order": 10 + int(p[1:]) * 2 + int(s), "video": None, "answers": [], "transcript_raw": ""}
    doc.update({"game": game, "hud": hud, "group": int(group)})
    doc.update(fields)
    write_doc("sessions", key, doc)
    rows = csv_rows(RAW / "session_log.csv")
    cols = ["participant", "group", "session", "game", "hud_condition", "start_time", "end_time", "notes"]
    rows = [r for r in rows if not (pid_ok(r["participant"]) == p and str(r["session"]) == str(int(s)))]
    rows.append({"participant": p, "group": group, "session": int(s), "game": game, "hud_condition": hud.capitalize(),
                 "start_time": "", "end_time": "", "notes": ""})
    rows.sort(key=lambda r: (r["participant"], int(r["session"])))
    RAW.mkdir(exist_ok=True)
    csv_write(RAW / "session_log.csv", rows, cols)


# ------------------------------------------------------------------ jobs
def start_job(name, commands):
    with LOCK:
        if JOB["running"]:
            return False
        JOB.update(name=name, running=True, log=[], code=None, started=time.time())

    def work():
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        code = 0
        for label, cmd in commands:
            if callable(cmd):
                try:
                    JOB["log"].append(cmd())
                except Exception as e:  # noqa: BLE001
                    JOB["log"].append(f"! {e}")
                    code = 1
                    break
                continue
            JOB["log"].append(f"--- {label}")
            pr = subprocess.Popen([sys.executable, "-u", *cmd], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace", env=env)
            for line in pr.stdout:
                JOB["log"].append(line.rstrip())
                del JOB["log"][:-400]
            pr.wait()
            if pr.returncode:
                code = pr.returncode
                JOB["log"].append(f"! stopped: {label} failed (code {code}). Read the lines above.")
                break
        JOB.update(running=False, code=code)

    threading.Thread(target=work, daemon=True).start()
    return True


def sync_app_to_raw():
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib
    mod = importlib.import_module("app_sync")
    tagsets = list_docs("tagsets")
    codesets = list_docs("codesets")
    if not tagsets and not codesets:
        return "No tags or codes in the app yet: keeping the CSV files already in raw/."
    # app_sync reads one JSON per document; our db folder already has that layout
    mod.import_export(str(DB))
    return "Tags and codes from the coding tab written to raw/."


def reset_dummy():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = ROOT / "_dummy_backup" / stamp
    bak.mkdir(parents=True, exist_ok=True)
    for name in ["clean", "results", "figures"]:
        if (ROOT / name).exists():
            shutil.move(str(ROOT / name), str(bak / name))
            (ROOT / name).mkdir()
    for f in RAW.glob("*.csv"):
        if f.name in ("interview_questions.csv", "aoi_regions.csv"):
            continue
        shutil.move(str(f), str(bak / f.name))
        t = STUDIO / "templates" / f.name
        if t.exists():
            shutil.copy(t, f)
    for d in ["transcripts", "gaze"]:
        if (RAW / d).exists():
            shutil.move(str(RAW / d), str(bak / d))
        (RAW / d).mkdir()
    if DB.exists():
        shutil.move(str(DB), str(bak / "studio_db"))
    ensure_practice()
    return f"Dummy data moved to {bak.name} inside _dummy_backup/. You now have empty files ready for real data."


def load_dummy():
    seed = ROOT / "app" / "seed"
    n = 0
    for f in sorted(seed.glob("*.json")):
        col, *rest = f.stem.split("__")
        d = json.loads(f.read_text(encoding="utf-8"))
        if col == "sessions" and d.get("kind") == "practice":
            continue
        if col == "sessions":
            d["video"] = None
        write_doc(col, "__".join(rest), d)
        n += 1
    return f"Loaded {n} dummy documents into the coding tab."


# ------------------------------------------------------------------ group sync (Supabase)
def sb_config():
    """Read url / key / group email out of app-supabase/supabase-config.js."""
    if not SB_CONFIG.exists():
        return None
    txt = SB_CONFIG.read_text(encoding="utf-8")
    get = lambda k: (re.search(rf'{k}\s*:\s*"([^"]*)"', txt) or [None, ""])[1]
    url, key, email = get("url").rstrip("/"), get("key"), get("groupEmail") or "group@hudstudy.com"
    if not url or url.startswith("PASTE") or key.startswith("PASTE"):
        return None
    return {"url": url, "key": key, "email": email}


def group_saved():
    try:
        return json.loads(GROUP_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def sb_call(cfg, path, method="GET", body=None, token=None, extra=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"apikey": cfg["key"], "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra or {})
    req = urllib.request.Request(cfg["url"] + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def sb_token(cfg, password):
    try:
        out = sb_call(cfg, "/auth/v1/token?grant_type=password", "POST", {"email": cfg["email"], "password": password})
        return out["access_token"], None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        if e.code in (400, 401):
            return None, "That group password was not accepted by Supabase."
        return None, f"Supabase said {e.code}: {detail}"
    except Exception as e:  # noqa: BLE001
        return None, f"Could not reach Supabase: {e}. Are you online?"


def group_connect(password, who=""):
    cfg = sb_config()
    if not cfg:
        return {"ok": False, "error": "No Supabase details found. Fill in app-supabase/supabase-config.js first."}
    token, err = sb_token(cfg, password)
    if err:
        return {"ok": False, "error": err}
    me = re.sub(r"[^a-z0-9]+", "-", (who or "").strip().lower()).strip("-")
    if not me:
        import socket
        me = re.sub(r"[^a-z0-9]+", "-", socket.gethostname().lower()).strip("-") or "studio"
    GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    GROUP_FILE.write_text(json.dumps({"password": password, "me": me}), encoding="utf-8")
    return {"ok": True, "me": me}


def group_ready():
    return bool(sb_config()) and bool(group_saved().get("password"))


def group_push():
    """Send this computer's study sessions (and their cleaned answers) up, so the group can tag them."""
    cfg = sb_config()
    token, err = sb_token(cfg, group_saved().get("password", ""))
    if err:
        raise RuntimeError(err)
    me = group_saved().get("me", "studio")
    rows, n_sess, n_work = [], 0, 0
    for d in list_docs("sessions"):
        body = dict(d["data"])
        body["video"] = None          # each coder opens their own copy of the recording
        rows.append({"collection": "sessions", "id": d["id"], "data": body})
        n_sess += 1
    # this computer's own tagging, renamed from "local" to this person, so it does not clash with anyone else's
    for col in ("tagsets", "codesets"):
        for d in list_docs(col):
            if not d["id"].endswith("__local"):
                continue              # pulled from someone else: never send it back
            body = dict(d["data"])
            body["by"] = me
            rows.append({"collection": col, "id": d["id"][: -len("local")] + me, "data": body})
            n_work += 1
    if not rows:
        return "Nothing to send: no sessions on this computer yet."
    for i in range(0, len(rows), 50):
        sb_call(cfg, "/rest/v1/docs", "POST", rows[i:i + 50], token, {"Prefer": "resolution=merge-duplicates,return=minimal"})
    return f"Sent {n_sess} sessions and {n_work} tagging records to the group."


def group_pull():
    """Bring the group's tags, codes and codebook down into this computer's store."""
    cfg = sb_config()
    token, err = sb_token(cfg, group_saved().get("password", ""))
    if err:
        raise RuntimeError(err)
    got = sb_call(cfg, "/rest/v1/docs?select=collection,id,data&collection=in.(sessions,tagsets,codesets,codebook)", token=token) or []
    me = group_saved().get("me", "studio")
    n_tags = n_codes = n_sess = 0
    for row in got:
        col, did, body = row["collection"], row["id"], row["data"]
        if col == "sessions":
            # a session this computer already has keeps its own copy: it holds the local video path and answers
            if read_doc("sessions", did) is None:
                write_doc("sessions", did, body)
                n_sess += 1
            continue
        if did.endswith("__local") or did.endswith("__" + me):
            continue              # this computer's own work, here or sent up earlier; never overwrite it
        write_doc(col, did, body)
        n_tags += len(body.get("tags", []))
        n_codes += len(body.get("items", []))
    extra = f", {n_sess} new sessions" if n_sess else ""
    return f"Got the group's work: {n_tags} tags and {n_codes} codes{extra}."


# ------------------------------------------------------------------ state for the UI
def state():
    ensure_practice()
    sessions = []
    for d in list_docs("sessions"):
        x = d["data"]
        if x.get("kind") != "study":
            continue
        key = d["id"]
        a = next((f for f in (RAW / "audio").glob(key + ".*")), None) if (RAW / "audio").exists() else None
        v = next((f for f in (RAW / "video").glob(key + ".*")), None) if (RAW / "video").exists() else None
        tr = (RAW / "transcripts" / f"{key}.txt").exists()
        sessions.append({"id": key, "participant": x["participant"], "session": x["session"], "game": x.get("game"), "hud": x.get("hud"),
                         "group": x.get("group"), "audio": a.name if a else None, "video": v.name if v else None,
                         "transcribed": tr, "answers": len(x.get("answers", []))})
    files = []
    for name, (what, why) in CSV_SLOTS.items():
        rows = csv_rows(RAW / name)
        files.append({"name": name, "what": what, "why": why, "rows": len(rows), "exists": (RAW / name).exists()})
    tags = sum(len(d["data"].get("tags", [])) for d in list_docs("tagsets") if d["data"].get("kind") != "practice")
    codes = sum(len(d["data"].get("items", [])) for d in list_docs("codesets"))
    figs = sorted(p.name for p in (ROOT / "figures").glob("*.png")) if (ROOT / "figures").exists() else []
    tables = sorted(p.name for p in (ROOT / "results").glob("*.csv")) if (ROOT / "results").exists() else []
    gaze = len(list((RAW / "gaze").glob("*.csv"))) if (RAW / "gaze").exists() else 0
    cfg = sb_config()
    if cfg:
        why = ""
    elif not SB_CONFIG.exists():
        why = f"{SB_CONFIG.name} was not found in the app-supabase folder."
    else:
        why = "The address or key in supabase-config.js is still the PASTE placeholder, or the line is not in the expected form."
    grp = {"configured": bool(cfg), "ready": group_ready(), "why": why, "me": group_saved().get("me", ""),
           "file": str(SB_CONFIG.relative_to(ROOT)), "url": (cfg or {}).get("url", ""), "email": (cfg or {}).get("email", "")}
    return {"group": grp, "sessions": sessions, "files": files, "tags": tags, "codes": codes, "figures": figs, "tables": tables, "gaze_files": gaze,
            "job": {"name": JOB["name"], "running": JOB["running"], "code": JOB["code"], "log": JOB["log"][-60:]}}


# ------------------------------------------------------------------ HTTP
class H(BaseHTTPRequestHandler):
    server_version = "HUDStudio"

    def log_message(self, *a):
        pass

    # --- responses
    def send_bytes(self, data, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, code=200):
        self.send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"), code=code)

    def send_file(self, path):
        path = Path(path)
        if not path.is_file():
            return self.send_bytes(b"not found", "text/plain", 404)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
            if not m.group(1) and m.group(2):
                start = max(0, size - int(m.group(2)))
                end = size - 1
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def jbody(self):
        b = self.body()
        return json.loads(b) if b else {}

    # --- routing
    def do_GET(self):
        u = urlparse(self.path)
        p, q = unquote(u.path), {k: v[0] for k, v in parse_qs(u.query).items()}
        if p == "/":
            return self.send_file(STUDIO / "ui.html")
        if p.startswith("/coding/"):
            return self.send_file(STUDIO / "coding" / (p[len("/coding/"):] or "index.html"))
        if p == "/coding":
            self.send_response(302); self.send_header("Location", "/coding/"); self.end_headers(); return
        if p.startswith("/practice/"):
            return self.send_file(ROOT / "practice" / Path(p).name)
        if p.startswith("/media/"):
            _, _, kind, name = p.split("/", 3)
            if kind in ("audio", "video"):
                return self.send_file(RAW / kind / Path(name).name)
        if p.startswith("/figures/"):
            return self.send_file(ROOT / "figures" / Path(p).name)
        if p.startswith("/table/"):
            f = ROOT / "results" / Path(p).name
            rows = csv_rows(f)
            return self.send_json({"name": f.name, "rows": rows[:200]})
        if p == "/api/state":
            return self.send_json(state())
        if p == "/api/transcript":
            f = RAW / "transcripts" / f"{q.get('id','')}.txt"
            review = [r for r in csv_rows(RAW / "transcripts" / "transcription_review.csv") if r.get("file", "").startswith(q.get("id", "-"))]
            return self.send_json({"text": f.read_text(encoding="utf-8") if f.exists() else "", "review": review})
        if p.startswith("/api/db/"):
            parts = p[len("/api/db/"):].split("/")
            if len(parts) == 1:
                return self.send_json(list_docs(parts[0]))
            return self.send_json({"data": read_doc(parts[0], parts[1])})
        if p.startswith("/api/template/"):
            f = STUDIO / "templates" / Path(p).name
            return self.send_file(f)
        self.send_bytes(b"not found", "text/plain", 404)

    def do_PUT(self):
        p = unquote(urlparse(self.path).path)
        if p.startswith("/api/db/"):
            col, id_ = p[len("/api/db/"):].split("/", 1)
            if not re.fullmatch(r"[\w\-]+", col) or not re.fullmatch(r"[\w\-]+", id_):
                return self.send_json({"error": "bad id"}, 400)
            write_doc(col, id_, self.jbody())
            return self.send_json({"ok": True})
        self.send_bytes(b"not found", "text/plain", 404)

    def do_POST(self):
        u = urlparse(self.path)
        p, q = unquote(u.path), {k: v[0] for k, v in parse_qs(u.query).items()}
        if p == "/api/upload":
            kind = q.get("kind")
            pp, s = pid_ok(q.get("participant", "")), q.get("session", "")
            if kind not in ("interview", "gameplay") or not pp or s not in ("1", "2"):
                self.body(); return self.send_json({"error": "Fill in participant (like P01) and session."}, 400)
            ext = Path(unquote(self.headers.get("X-Filename", "x.mp4"))).suffix.lower()
            if ext not in AUDIO_EXT:
                self.body(); return self.send_json({"error": f"Can't use {ext or 'this'} file type."}, 400)
            folder = RAW / ("audio" if kind == "interview" else "video")
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(sid(pp, s) + ".*"):
                old.unlink()
            dest = folder / f"{sid(pp, s)}{ext}"
            left = int(self.headers.get("Content-Length") or 0)
            with open(dest, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            extra = {"video": f"/media/video/{dest.name}"} if kind == "gameplay" else {}
            register_session(pp, s, q.get("game", ""), q.get("hud", "").lower(), q.get("group", "1"), **extra)
            return self.send_json({"ok": True, "saved": dest.name})
        if p == "/api/session":
            d = self.jbody()
            pp = pid_ok(d.get("participant", ""))
            if not pp:
                return self.send_json({"error": "bad participant"}, 400)
            register_session(pp, d["session"], d["game"], d["hud"].lower(), d["group"])
            return self.send_json({"ok": True})
        if p == "/api/transcribe":
            d = self.jbody()
            key = d["id"]
            pp, s = key.split("_S")
            model = d.get("model", "small")
            ok = start_job(f"Transcribe {key}", [
                (f"Whisper ({model}) on {key}", ["scripts/transcribe.py", "--only", key, "--overwrite", "--model", model,
                                                  "--language", d.get("language", "en")]),
                ("", lambda: f"Transcript ready: {refresh_session_from_transcript(pp, int(s))} answers found.")])
            return self.send_json({"ok": ok, "busy": not ok})
        if p == "/api/transcript":
            d = self.jbody()
            key = d["id"]
            (RAW / "transcripts").mkdir(parents=True, exist_ok=True)
            (RAW / "transcripts" / f"{key}.txt").write_text(d["text"], encoding="utf-8")
            pp, s = key.split("_S")
            n = refresh_session_from_transcript(pp, int(s))
            return self.send_json({"ok": True, "answers": n})
        if p == "/api/upload_csv":
            name = Path(q.get("name", "")).name
            if name not in CSV_SLOTS:
                self.body(); return self.send_json({"error": "unknown file"}, 400)
            data = self.body()
            RAW.mkdir(exist_ok=True)
            (RAW / name).write_bytes(data)
            return self.send_json({"ok": True, "rows": len(csv_rows(RAW / name))})
        if p == "/api/group/connect":
            d = self.jbody()
            return self.send_json(group_connect(d.get("password", ""), d.get("who", "")))
        if p == "/api/group/push":
            self.body()
            return self.send_json({"ok": start_job("Send sessions to the group", [("", group_push)])})
        if p == "/api/group/pull":
            self.body()
            return self.send_json({"ok": start_job("Get the group's work", [("", group_pull)])})
        if p == "/api/run":
            d = self.jbody()
            cmds = []
            if d.get("pull") and group_ready():
                cmds.append(("", group_pull))
            if d.get("use_app", True):
                cmds.append(("", sync_app_to_raw))
            cmds.append(("Cleaning, gaze, keywords, analysis", ["scripts/run_all.py"]))
            return self.send_json({"ok": start_job("Run analysis", cmds)})
        if p == "/api/reset":
            self.body()
            return self.send_json({"ok": True, "message": reset_dummy()})
        if p == "/api/load_dummy":
            self.body()
            return self.send_json({"ok": True, "message": load_dummy()})
        if p == "/api/open_folder":
            name = q.get("name", "")
            if name in ("results", "figures", "raw", "clean"):
                try:
                    os.startfile(ROOT / name)  # type: ignore[attr-defined]  (Windows)
                except AttributeError:
                    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(ROOT / name)])
            return self.send_json({"ok": True})
        self.send_bytes(b"not found", "text/plain", 404)


def main():
    DB.mkdir(parents=True, exist_ok=True)
    ensure_practice()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print(f"HUD Study Studio running at {url}\nLeave this window open while you work. Close it to stop.")
    if not os.environ.get("HUD_NO_BROWSER"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
