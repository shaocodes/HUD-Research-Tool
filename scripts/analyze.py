"""
analyze.py — step 5: results
----------------------------
Descriptive, within-participant comparison of full vs minimal HUD, suited to a
small contextual inquiry (about 8 participants): for each measure, the median in
each condition, how many participants moved the same way ("6 of 7 higher with the
minimal HUD") and the rank-biserial r. A Wilcoxon p-value is reported as
exploratory only: with 8 people even a unanimous change gives p = 0.008, so
results are read from the direction counts and the interviews, not from p.

  A  full vs minimal on every measure
  B  does the pattern hold in both games?
  C  by gaming expertise (CI-RQ2)
  D  coder agreement (Cohen's kappa, 10-s windows of active play)
  E  practice clips: each tagger vs the reference answer key
  F  interview themes by condition + saturation
  G  gaze share per area of interest

Outputs: results/*.csv, figures/*.png, results/dashboard/*.json
Run:  python scripts/analyze.py
"""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parent.parent
CLEAN, RES, FIG, PRAC, RAW = ROOT / "clean", ROOT / "results", ROOT / "figures", ROOT / "practice", ROOT / "raw"
DASH = RES / "dashboard"
for d in (RES, FIG, DASH):
    d.mkdir(exist_ok=True, parents=True)

BIN_S = 10
SATURATION_RUN = 3
MATCH_WINDOW_S = 3       # a practice tag counts if within 3 s of the reference event

m = pd.read_csv(CLEAN / "session_metrics.csv")
log = pd.read_csv(CLEAN / "cleaning_log.csv")
iv = pd.read_csv(CLEAN / "interview_codes.csv")

MEASURES = [
    ("Full-map opens", "full_map_open_per_min", "per min", "Comprehension"),
    ("Navigation errors", "navigation_error_per_min", "per min", "Comprehension"),
    ("Hesitations", "hesitation_per_min", "per min", "Comprehension"),
    ("Missed prompts", "missed_prompt_per_min", "per min", "Comprehension"),
    ("Unintended actions", "unintended_action_per_min", "per min", "Comprehension"),
    ("Time to objective", "time_to_objective_s", "s", "Comprehension"),
    ("Objective completion", "objective_completion", "proportion", "Comprehension"),
    ("SA accuracy (all)", "sa_accuracy", "proportion", "Comprehension"),
    ("SA perception", "sa_perception", "proportion", "Comprehension"),
    ("SA comprehension", "sa_comprehension", "proportion", "Comprehension"),
    ("SA projection", "sa_projection", "proportion", "Comprehension"),
    ("Menu breaks", "menu_break_per_min", "per min", "Immersion"),
    ("Gaze on game world", "gaze_game_world", "share", "Immersion"),
]


def paired(col):
    return m.pivot_table(index="participant", columns="hud", values=col).dropna()


def rank_biserial(d):
    d = d[d != 0]
    if len(d) == 0:
        return 0.0
    r = pd.Series(np.abs(d)).rank().values
    return (r[d > 0].sum() - r[d < 0].sum()) / r.sum()


# A ---------------------------------------------------------------------------
rows = []
for name, col, unit, dv in MEASURES:
    w = paired(col)
    d = (w["minimal"] - w["full"]).values
    p = wilcoxon(w["minimal"], w["full"]).pvalue if np.any(d != 0) and len(d) > 1 else np.nan
    rows.append({"measure": name, "column": col, "unit": unit, "indicates": dv, "n_pairs": len(w),
                 "full_median": w["full"].median(), "minimal_median": w["minimal"].median(),
                 "median_change": np.median(d), "higher_in_minimal": int((d > 0).sum()),
                 "lower_in_minimal": int((d < 0).sum()), "no_change": int((d == 0).sum()),
                 "rank_biserial_r": rank_biserial(d), "p_exploratory": p})
A = pd.DataFrame(rows)
A["direction"] = np.select([A["higher_in_minimal"] >= A["n_pairs"] - 1, A["lower_in_minimal"] >= A["n_pairs"] - 1],
                           ["higher with minimal (all or all but one)", "lower with minimal (all or all but one)"],
                           "mixed")
A.round(4).to_csv(RES / "A_full_vs_minimal.csv", index=False)

# B ---------------------------------------------------------------------------
B = []
for name, col, unit, dv in MEASURES:
    for game in ["GTA V", "Cyberpunk 2077"]:
        for hud in ["full", "minimal"]:
            v = m[(m["game"] == game) & (m["hud"] == hud)][col].dropna()
            B.append({"measure": name, "column": col, "game": game, "hud": hud, "median": v.median(), "n": len(v)})
B = pd.DataFrame(B)
B.round(4).to_csv(RES / "B_by_game.csv", index=False)

# C ---------------------------------------------------------------------------
grp = m.drop_duplicates("participant").set_index("participant")["expertise_group"]
C = []
for name, col, unit, dv in MEASURES:
    w = paired(col)
    d = w["minimal"] - w["full"]
    for g in ["Less experienced", "More experienced"]:
        dd = d[grp.reindex(d.index) == g]
        C.append({"measure": name, "column": col, "expertise_group": g, "n": len(dd), "median_change": dd.median()})
C = pd.DataFrame(C)
C.round(4).to_csv(RES / "C_by_expertise.csv", index=False)

# D coder agreement ------------------------------------------------------------
ev_a = pd.read_csv(CLEAN / "gameplay_events.csv")
ev_b = pd.read_csv(CLEAN / "gameplay_events_coderB.csv")
skips = pd.read_csv(CLEAN / "skipped_segments.csv")
D = []
pooled_a, pooled_b = [], []
double = ev_b[["participant", "session"]].drop_duplicates()
for ev in sorted(set(ev_a["event"]) - {"objective_received", "objective_reached"}):
    va, vb = [], []
    for p, s in double.itertuples(index=False):
        bins = np.arange(0, 1800 + BIN_S, BIN_S)
        seg = skips[(skips["participant"] == p) & (skips["session"] == s)]
        keep = np.ones(len(bins) - 1, bool)
        for a, b in zip(seg["start_s"], seg["end_s"]):
            keep &= ~((bins[:-1] >= a) & (bins[:-1] < b))
        for src, vec in ((ev_a, va), (ev_b, vb)):
            t = src[(src["participant"] == p) & (src["session"] == s) & (src["event"] == ev)]["t_s"]
            x = np.zeros(len(bins) - 1, int)
            x[np.clip((t // BIN_S).astype(int), 0, len(x) - 1)] = 1
            vec.extend(x[keep])
    D.append({"event": ev, "kappa": cohen_kappa_score(va, vb), "agreement": float(np.mean(np.equal(va, vb)))})
    pooled_a += va
    pooled_b += vb
D.append({"event": "all events", "kappa": cohen_kappa_score(pooled_a, pooled_b),
          "agreement": float(np.mean(np.equal(pooled_a, pooled_b)))})
D = pd.DataFrame(D)
D.round(3).to_csv(RES / "D_coder_agreement.csv", index=False)

# E practice clips vs reference ------------------------------------------------
E = pd.DataFrame()
ref = pd.read_csv(PRAC / "reference_events.csv")
ptags_path = RAW / "practice_tags.csv"
if ptags_path.exists():
    pt = pd.read_csv(ptags_path)
    out = []
    for (who, clip), g in pt.groupby(["tagged_by", "clip"]):
        r = ref[ref["clip"] == clip]
        used, hits = set(), 0
        for _, re_ in r.iterrows():
            cand = g[(g["event"] == re_["event"]) & ((g["t_s"] - re_["t_s"]).abs() <= MATCH_WINDOW_S)]
            cand = cand[~cand.index.isin(used)]
            if len(cand):
                used.add(cand.index[0])
                hits += 1
        out.append({"tagged_by": who, "clip": clip, "reference_events": len(r), "found": hits,
                    "missed": len(r) - hits, "extra_tags": len(g) - len(used),
                    "recall": hits / len(r) if len(r) else np.nan})
    E = pd.DataFrame(out)
    E.round(3).to_csv(RES / "E_practice_vs_reference.csv", index=False)

# F themes + saturation --------------------------------------------------------
n_p = m["participant"].nunique()
coded = iv[iv["participant"].isin(m["participant"])]
F = (coded.groupby(["theme", "hud"])["participant"].nunique().unstack(fill_value=0)
     .reindex(columns=["full", "minimal"], fill_value=0) / n_p)
F.columns = ["share_full", "share_minimal"]
F["mentions"] = coded.groupby("theme").size()
F = F.sort_values("mentions", ascending=False).reset_index()
F.round(3).to_csv(RES / "F_themes_by_condition.csv", index=False)
seen, S = set(), []
for i, pid in enumerate(sorted(coded["participant"].unique()), start=1):
    new = set(coded.loc[coded["participant"] == pid, "code"]) - seen
    seen |= new
    S.append({"order": i, "participant": pid, "new_codes": len(new), "cumulative_codes": len(seen)})
S = pd.DataFrame(S)
run, sat = 0, None
for r in S.itertuples():
    run = run + 1 if r.new_codes == 0 else 0
    if run >= SATURATION_RUN and sat is None:
        sat = r.order
S.to_csv(RES / "F_saturation.csv", index=False)

# G gaze -------------------------------------------------------------------------
gz = pd.read_csv(CLEAN / "gaze_aoi.csv")
G = gz.groupby(["game", "hud", "aoi"])["share"].median().reset_index()
G.round(4).to_csv(RES / "G_gaze_share.csv", index=False)

# figures --------------------------------------------------------------------------
C_FULL, C_MIN, INK, INK2, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 8.5, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(1, 4, figsize=(7.2, 2.5))
for ax, (col, title, unit) in zip(axes, [("full_map_open_per_min", "Full-map opens", "per active min"),
                                         ("navigation_error_per_min", "Navigation errors", "per active min"),
                                         ("time_to_objective_s", "Time to objective", "seconds"),
                                         ("sa_comprehension", "SA comprehension", "proportion correct")]):
    w = paired(col)
    for _, r in w.iterrows():
        ax.plot([0, 1], [r["full"], r["minimal"]], color=GRID, lw=1.2, zorder=1)
    ax.scatter(np.zeros(len(w)), w["full"], s=24, color=C_FULL, zorder=3, edgecolor="white")
    ax.scatter(np.ones(len(w)), w["minimal"], s=24, color=C_MIN, zorder=3, edgecolor="white")
    for x, v in ((0, w["full"].median()), (1, w["minimal"].median())):
        ax.plot([x - .2, x + .2], [v, v], color=INK, lw=2.2, zorder=4)
    row = A[A["column"] == col].iloc[0]
    ax.set_title(f"{title}\n{row.higher_in_minimal} of {row.n_pairs} higher with minimal", fontsize=8.5, loc="left", color=INK)
    ax.set_xticks([0, 1], ["Full", "Minimal"])
    ax.set_xlim(-.5, 1.5)
    ax.set_ylabel(unit)
    ax.grid(axis="y", color=GRID, lw=.6)
fig.tight_layout()
fig.savefig(FIG / "fig_paired_measures.png", dpi=300)
plt.close(fig)

fig, ax = plt.subplots(figsize=(3.6, 2.6))
y = np.arange(len(F))
ax.barh(y - .19, F["share_full"] * 100, height=.36, color=C_FULL, label="Full HUD")
ax.barh(y + .19, F["share_minimal"] * 100, height=.36, color=C_MIN, label="Minimal HUD")
ax.set_yticks(y, F["theme"])
ax.invert_yaxis()
ax.set_xlabel("% of participants raising the theme")
ax.set_title("Themes by HUD condition", fontsize=9.5, loc="left", color=INK)
ax.legend(frameon=False, fontsize=7.5, loc="lower right")
fig.tight_layout()
fig.savefig(FIG / "fig_themes.png", dpi=300)
plt.close(fig)

fig, ax = plt.subplots(figsize=(3.4, 2.4))
ax.bar(S["order"], S["new_codes"], color=GRID, width=.6)
ax.plot(S["order"], S["cumulative_codes"], color=C_FULL, lw=2, marker="o", ms=4)
if sat:
    ax.axvline(sat, color=INK2, lw=1, ls="--")
ax.set_xlabel("Participant (order of participation)")
ax.set_ylabel("Codes")
ax.set_title("New and total interview codes", fontsize=9.5, loc="left", color=INK)
fig.tight_layout()
fig.savefig(FIG / "fig_saturation.png", dpi=300)
plt.close(fig)

# dashboard files --------------------------------------------------------------------


def dump(df, name):
    (DASH / name).write_text(df.to_json(orient="records", double_precision=6))


dump(m, "sample_session_metrics.json")
dump(A, "sample_full_vs_minimal.json")
dump(B, "sample_by_game.json")
dump(C, "sample_by_expertise.json")
dump(D, "sample_coder_agreement.json")
dump(F, "sample_themes.json")
dump(S.assign(saturation_point=sat), "sample_saturation.json")
dump(pd.read_csv(CLEAN / "gaze_grid.csv"), "sample_gaze_grid.json")
dump(G, "sample_gaze_share.json")
dump(pd.read_csv(RES / "K_keywords_by_condition.csv"), "sample_keywords.json")
dump(pd.read_csv(CLEAN / "cleaning_log.csv"), "sample_cleaning_log.json")
gp = m[["participant", "session", "game", "hud", "active_min", "skipped_static_min", "skipped_no_gameplay_min",
        "skipped_corrupted_min", "gameplay_usable"]]
dump(gp, "sample_footage.json")
if len(E):
    dump(E, "sample_practice_check.json")

pd.set_option("display.width", 200)
print(A[["measure", "n_pairs", "full_median", "minimal_median", "higher_in_minimal", "rank_biserial_r"]].round(3).to_string(index=False))
print("kappa (all events):", round(D.iloc[-1]["kappa"], 2), "| saturation at participant", sat)
if len(E):
    print(E.to_string(index=False))
