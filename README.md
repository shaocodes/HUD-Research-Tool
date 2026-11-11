# HUD Research Tool

Tools for a contextual-inquiry study on how HUD design affects player interaction in open-world games
(full vs minimal HUD, GTA V and Cyberpunk 2077, within-subjects, counterbalanced).

| Part | What it is |
|---|---|
| `app-supabase/` | Web app where the research group tags gameplay and codes interviews together (static page + Supabase database, free tier). Setup: `app-supabase/SETUP.md` |
| `scripts/` | Python pipeline: Whisper transcription, cleaning, gaze processing, keywords, descriptive analysis |
| `dashboard/` | Results dashboard page |
| `raw/`, `clean/`, `results/`, `figures/` | **Dummy data** generated to test the pipeline. No real participant data is in this repository |

> All data in this repository is synthetic. Real recordings, names and the participant roster are kept out (see `.gitignore`).

<!-- Add screenshots here:  ![Coding app](docs/coding-app.png)  ![Dashboard](docs/dashboard.png) -->

---

# HUD study: data pipeline

Cleaning, processing and analysis for the HUD contextual inquiry
(full vs minimal HUD, GTA V and Cyberpunk 2077, four counterbalancing groups, about 8 participants).

**Everything in `raw/` is DUMMY data**, generated to test the pipeline. It contains
deliberate mistakes so every cleaning step has something to fix. Replace it with your
real exports, keeping the same file names and columns.

## Easiest way: the Studio (no command line)

1. Install Python once (python.org, tick **Add python.exe to PATH**), then double-click **`Setup (run once).bat`**.
2. Double-click **`Start.bat`**. A page opens in your browser (everything stays on your computer).
3. **Recordings** tab: drop an interview recording, pick participant and session, click **Transcribe** (Whisper).
4. **Tag & code** tab: tag gameplay and code interviews.
5. **Run & results** tab: fill in the checklist, click **Run analysis**, see tables and figures.

The project starts with dummy data. **Start fresh** (Run & results tab) moves it to a backup folder.

---

## The workflow with real data

| Step | Who | What |
|---|---|---|
| 1. Collect | Group | OBS recording + webcam gaze export per session, interview audio, form exports (screening, SA answers) |
| 2. Transcribe | `transcribe.py` (Whisper, offline) | Audio in `raw/audio/` → one text file per interview in `raw/transcripts/`; check the flagged spots by ear |
| 3. Tag gameplay | Group, in the **HUD Study Coding** app | Open each recording, press keys to tag events, mark skipped segments. A second coder tags ~25 % of sessions as Coder B |
| 4. Code interviews | Group, in the app | Select text in cleaned answers and assign codes from the shared codebook |
| 5. Answer key | Group | Watch the end of each recording and fill `raw/sa_answer_key.csv` |
| 6. Export | App → `raw/` | Data tab → Export CSV for tags, skipped segments, codes, practice tags (or ask Claude to pull them) |
| 7. Run | Script | `python scripts/run_all.py` |
| 8. Present | Dashboard | Send the new `results/dashboard/*.json` to Claude to update the HUD Study Results dashboard |

Practice first: the app has two practice clips (`practice/`). Tag them, export
`practice_tags.csv` into `raw/`, and `analyze.py` scores each tagger against the
reference answer key (`practice/reference_events.csv`): found, missed, extra tags.

## Transcribing interviews (Whisper, on your own computer)

One-time setup on the PC that transcribes (about 700–850 MB with the small model):

1. Install Python 3.10 or newer from python.org (Windows: tick **"Add python.exe to PATH"**).
2. Open a terminal in this folder and run `pip install -r requirements.txt`.
3. Run `python scripts/transcribe.py` once; it downloads the Whisper "small" model (~500 MB) the first time, then works offline.

Each time:

1. Name recordings `P01_S1.m4a`, `P01_S2.m4a`, … and put them in `raw/audio/` (mp3, m4a, wav, mp4 all work).
2. `python scripts/transcribe.py` → transcripts appear in `raw/transcripts/`.
3. Open `raw/transcripts/transcription_review.csv` and listen to the flagged times (questions not found, unclear audio, very short answers). Fix the .txt files if needed.
4. `python scripts/run_all.py`.

**Interview habit:** start each question with its number ("Question three. Which HUD elements…").
The script splits answers at those words. If a number is forgotten, it still finds the
question by its wording and flags it for checking. Questions 9–12 are expected only in
session-2 recordings (the final, after-both-sessions questions).

The audio never leaves the computer. Whisper skips silence by itself, and `clean_transcripts.py`
then removes fillers and names as before.

## Run it

```
pip install pandas numpy scipy scikit-learn matplotlib
python scripts/run_all.py
```

`run_all.py` runs, in order:

| Script | Does |
|---|---|
| `clean.py` | Forms (IDs, duplicates, screening, hours), session check against the counterbalancing table (dropouts and wrong presets excluded), gameplay (merges skipped segments → **active play time**; drops duplicate tags, tags after the session ended and tags inside skipped segments; flags sessions with < 50 % usable footage), event rates per active minute, time to objective, SA scoring, codebook spelling |
| `clean_transcripts.py` | Removes `[silence Ns]` markers and fillers (uh, um, and *like,* / *you know,* only when used as fillers), anonymises names and gamer tags using the private roster, splits answers by question, builds the **participant × question table**, checks every coded excerpt still matches the cleaned text |
| `gaze.py` | Removes blink, low-confidence (< 0.6) and off-screen samples and samples inside skipped segments; drops sessions with < 60 % usable samples; assigns samples to HUD areas of interest; builds heatmaps |
| `keywords.py` | Keeps meaningful words (common words removed, **negations kept**: "not sure" → `not_sure`), counts them per HUD condition and question, ranks the words most typical of each condition |
| `analyze.py` | Descriptive full vs minimal comparison (medians, "k of n moved the same way", rank-biserial r, exploratory p), by game, by expertise, coder agreement (Cohen's κ), practice-clip check, themes, saturation, gaze shares; writes figures and the dashboard files |

Other scripts: `generate_dummy_data.py` (rebuilds the dummy `raw/`),
`make_practice_clips.py` (rebuilds the practice videos and their answer key),
`app_sync.py` (`seed` builds the app's starting data; `import <folder>` turns the app's
database into the `raw/` CSVs).

## Folders

| Folder | Contents |
|---|---|
| `raw/` | What you collect. `participant_roster.csv` holds real names: keep it private and never upload it |
| `clean/` | Tidy tables. `session_metrics.csv` = one row per participant × session with every measure; `cleaning_log.csv` = every fix and exclusion (report these in the paper); `transcripts/` = cleaned, anonymised transcripts (safe to share); `interview_table.csv` = participant × question |
| `results/` | Analysis tables A–G and K, plus `dashboard/*.json` |
| `figures/` | 300-dpi PNGs for the paper: paired measures, themes, saturation, keywords, gaze heatmaps |
| `practice/` | Practice clips and their reference answer key |
| `app/` | The coding app page, its practice clips and seed data |
| `dashboard/` | The results dashboard page |

## Settings you may want to change

Top of each script: `MIN_USABLE_SHARE` (0.5), `EXPERT_CUTOFF` (4), `MIN_CONFIDENCE` (0.6),
`MIN_VALID_SHARE` (0.6), `BIN_S` (10 s), `SATURATION_RUN` (3), `MATCH_WINDOW_S` (3 s).
`raw/aoi_regions.csv` holds **placeholder** HUD box positions: measure the real ones
from a screenshot of each game and HUD setting before running the study.
