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
  H  hypothesis tests (Wilcoxon signed-rank, Bonferroni alpha = 0.05/3) + power
     -- read as association ("participants with the full HUD tended to ..."),
        never as cause; edit HYPOTHESES below to match the RQs

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
from scipy.stats import wilcoxon, norm, nct, t as t_dist
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parent.parent
CLEAN, RES, FIG, PRAC, RAW = ROOT / "clean", ROOT / "results", ROOT / "figures", ROOT / "practice", ROOT / "raw"
DASH = RES / "dashboard"
for d in (RES, FIG, DASH):
    d.mkdir(exist_ok=True, parents=True)

BIN_S = 10
SATURATION_RUN = 3
MATCH_WINDOW_S = 3       # a practice tag counts if within 3 s of the reference event

# ---- hypotheses: edit to match the research questions ------------------------------
# (label, column in session_metrics, what the hypothesis says, RQ it answers)
HYPOTHESES = [
    ("H1", "navigation_error_per_min", "Navigation errors per active minute differ between full and minimal HUD", "RQ (comprehension)"),
    ("H2", "sa_accuracy", "Situation-awareness accuracy differs between full and minimal HUD", "RQ (comprehension)"),
    ("H3", "gaze_game_world", "Share of gaze on the game world differs between full and minimal HUD", "RQ (immersion)"),
]
ALPHA = 0.05                   # family-wise, two-tailed
LIT_EFFECT_D = 0.8             # expected effect size from related literature (Cohen's d_z); replace with the cited value
POWER_TARGET = 0.80

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
legend = pd.read_csv(CLEAN / "legend.csv")
EV = legend[legend["column"] == "event"].set_index("code")["label"].to_dict()
for d_ in (ev_a, ev_b):
    d_["t_s"] = d_["t_ms"] / 1000
not_rated = {c for c, l in EV.items() if l in ("objective_received", "objective_reached")}
for ev in sorted(set(ev_a["event"]) - not_rated):
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
    D.append({"event": EV.get(ev, ev), "event_code": ev, "kappa": cohen_kappa_score(va, vb), "agreement": float(np.mean(np.equal(va, vb)))})
    pooled_a += va
    pooled_b += vb
D.append({"event": "all events", "kappa": cohen_kappa_score(pooled_a, pooled_b),
          "agreement": float(np.mean(np.equal(pooled_a, pooled_b)))})
D = pd.DataFrame(D)
D.round(3).to_csv(RES / "D_coder_agreement.csv", index=False)

# E practice clips vs reference ------------------------------------------------
E = pd.DataFrame()
ptags_path = RAW / "practice_tags.csv"
if ptags_path.exists() and (PRAC / "reference_events.csv").exists():
    ref = pd.read_csv(PRAC / "reference_events.csv")
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


# H hypothesis tests + power ----------------------------------------------------------
K = len(HYPOTHESES)
alpha_tail = ALPHA / 2 / K                 # 0.025 / 3
z_crit = norm.ppf(1 - alpha_tail)          # value read from the z-table


def ttest_power(d, n, alpha_two):
    """Power of a two-sided paired t-test for effect d_z with n pairs (Wilcoxon is ~95% as efficient)."""
    n_eff = n * 3 / np.pi                  # asymptotic relative efficiency of Wilcoxon vs t
    df = max(n_eff - 1, 1)
    tc = t_dist.ppf(1 - alpha_two / 2, df)
    nc = d * np.sqrt(n_eff)
    return float(1 - nct.cdf(tc, df, nc) + nct.cdf(-tc, df, nc))


def min_detectable_d(n, alpha_two, power=POWER_TARGET):
    lo, hi = 0.01, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ttest_power(mid, n, alpha_two) < power else (lo, mid)
    return hi


def n_needed(d, alpha_two, power=POWER_TARGET):
    for n in range(3, 500):
        if ttest_power(d, n, alpha_two) >= power:
            return n
    return np.nan


LABEL = {c: f"{nm} ({u})" for nm, c, u, _ in MEASURES}
H, Hp = [], []
for hid, col, text, rq in HYPOTHESES:
    w = paired(col)
    d = (w["full"] - w["minimal"]).values         # positive = higher with full HUD
    nz = d[d != 0]
    n = len(nz)
    if n < 2:
        continue
    res = wilcoxon(w["full"], w["minimal"], method="exact" if n <= 25 else "approx")
    ranks = pd.Series(np.abs(nz)).rank().values
    w_plus = ranks[nz > 0].sum()
    mu, sd = n * (n + 1) / 4, np.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w_plus - mu) / sd                         # normal approximation, for the z-table
    dz = d.mean() / d.std(ddof=1) if d.std(ddof=1) > 0 else np.nan
    sig = res.pvalue < 2 * alpha_tail             # exact p decides; z is the large-sample check (conservative at n < 10)
    higher = "higher" if np.median(d) > 0 else "lower"
    if sig:
        reading = (f"Participants with the full HUD tended to have {higher} {LABEL.get(col, col).lower()} "
                   f"(z = {z:.2f}, p = {res.pvalue:.3f}); an association, not evidence of cause.")
    else:
        reading = (f"No reliable difference detected (z = {z:.2f}, p = {res.pvalue:.3f}, needed p < {2 * alpha_tail:.4f}, i.e. |z| > {z_crit:.2f}); "
                   f"with n = {len(d)} only large effects are detectable, so this is 'not detected', not 'no effect'. "
                   f"See interview themes for why.")
    H.append({"hypothesis": hid, "rq": rq, "statement": text, "measure": col, "n_pairs": len(d),
              "full_median": w["full"].median(), "minimal_median": w["minimal"].median(),
              "higher_with_full": int((d > 0).sum()), "lower_with_full": int((d < 0).sum()),
              "W_plus": w_plus, "z": z, "z_critical": z_crit, "p_two_sided": res.pvalue,
              "alpha_per_test": 2 * alpha_tail, "significant": bool(sig),
              "effect_r": z / np.sqrt(n), "rank_biserial_r": rank_biserial(d), "observed_d_z": dz,
              "observed_power": (np.nan_to_num(ttest_power(abs(dz), len(d), 2 * alpha_tail), nan=1.0)
                                 if np.isfinite(dz) else np.nan),
              "reading": reading})
    Hp.append(len(d))
H = pd.DataFrame(H)
H.round(4).to_csv(RES / "H_hypothesis_tests.csv", index=False)

n_cur = int(np.median(Hp)) if Hp else m["participant"].nunique()
smallest_p = 2 / 2 ** n_cur                   # every participant moves the same way
P = pd.DataFrame([
    {"item": "Participants (pairs) per test", "value": n_cur},
    {"item": "Hypotheses tested (Bonferroni k)", "value": K},
    {"item": "Alpha per tail (0.025 / k)", "value": round(alpha_tail, 5)},
    {"item": "Critical z (z-table)", "value": round(z_crit, 3)},
    {"item": "Smallest possible p with this n (all move one way)", "value": round(smallest_p, 5)},
    {"item": f"Smallest detectable effect d_z at {int(POWER_TARGET * 100)}% power", "value": round(min_detectable_d(n_cur, 2 * alpha_tail), 2)},
    {"item": f"Power for literature effect d_z = {LIT_EFFECT_D}", "value": round(ttest_power(LIT_EFFECT_D, n_cur, 2 * alpha_tail), 3)},
    {"item": f"Pairs needed for {int(POWER_TARGET * 100)}% power at d_z = {LIT_EFFECT_D}", "value": n_needed(LIT_EFFECT_D, 2 * alpha_tail)},
])
P.to_csv(RES / "H_power.csv", index=False)

# coded copy of the final metrics (gaze included) -------------------------------------
_leg = pd.read_csv(CLEAN / "legend.csv")
mc = m.copy()
for col, g in _leg.groupby("column"):
    if col in mc.columns:
        mc[col] = mc[col].astype(str).map(dict(zip(g["label"], g["code"]))).astype("Int64")
for c in mc.columns:
    if mc[c].dtype == bool:
        mc[c] = mc[c].astype(int)
mc.round(4).to_csv(CLEAN / "session_metrics_coded.csv", index=False)

# figures --------------------------------------------------------------------------
C_FULL, C_MIN, INK, INK2, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 12, "axes.titlesize": 13, "axes.labelsize": 12, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(1, 4, figsize=(15, 5))
for ax, (col, title, unit) in zip(axes, [("full_map_open_per_min", "Full-map opens", "Times the full map was opened\nper minute of play  (higher = checked more)"),
                                         ("navigation_error_per_min", "Navigation errors", "Wrong turns / navigation mistakes\nper minute of play  (higher = more lost)"),
                                         ("time_to_objective_s", "Time to objective", "Seconds to reach the objective\n(higher = slower)"),
                                         ("sa_comprehension", "SA comprehension", "HUD questions answered correctly (%)\n(higher = understood more)")]):
    w = paired(col)
    if col.startswith("sa_"):
        w = w * 100                               # proportion -> percent
    jit = (np.arange(len(w)) - (len(w) - 1) / 2) * (0.30 / max(len(w) - 1, 1))
    for j, (_, r) in zip(jit, w.iterrows()):
        ax.plot([0 + j, 1 + j], [r["full"], r["minimal"]], color="#b9b7b0", lw=1.4, zorder=1)
    ax.scatter(jit, w["full"], s=60, color=C_FULL, zorder=3, edgecolor="white", label="Full HUD")
    ax.scatter(1 + jit, w["minimal"], s=60, color=C_MIN, zorder=3, edgecolor="white", label="Minimal HUD")
    for x, v in ((0, w["full"].median()), (1, w["minimal"].median())):
        ax.plot([x - .28, x + .28], [v, v], color=INK, lw=3, zorder=4)
    row = A[A["column"] == col].iloc[0]
    ax.set_title(f"{title}\n{row.higher_in_minimal} of {row.n_pairs} higher with minimal", loc="left", color=INK)
    ax.set_xticks([0, 1], ["Full HUD", "Minimal HUD"])
    ax.set_xlim(-.55, 1.55)
    ax.set_xlabel("HUD condition")
    ax.set_ylabel(unit)
    ax.grid(axis="y", color=GRID, lw=.6)
fig.text(0.01, 0.01, "Each dot is one participant; grey lines join the same person's two sessions; black bars are medians. "
         "'Per minute of play' counts only active gameplay (idle and loading time removed).",
         fontsize=10.5, color=INK2)
fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(FIG / "fig_paired_measures.png", dpi=300)
plt.close(fig)

fig, ax = plt.subplots(figsize=(9, 5.5))
y = np.arange(len(F))
ax.barh(y - .19, F["share_full"] * 100, height=.36, color=C_FULL, label="Full HUD")
ax.barh(y + .19, F["share_minimal"] * 100, height=.36, color=C_MIN, label="Minimal HUD")
ax.set_yticks(y, F["theme"])
ax.invert_yaxis()
ax.set_xlabel("Participants raising the theme (%)")
ax.set_title("Themes by HUD condition", loc="left", color=INK)
ax.legend(frameon=False, loc="lower right")
fig.tight_layout()
fig.savefig(FIG / "fig_themes.png", dpi=300)
plt.close(fig)

fig, ax = plt.subplots(figsize=(8.5, 5))
ax.bar(S["order"], S["new_codes"], color="#c9c7c0", width=.6, label="New codes from this participant")
ax.plot(S["order"], S["cumulative_codes"], color=C_FULL, lw=2.5, marker="o", ms=7, label="Total distinct codes")
if sat:
    ax.axvline(sat, color=INK2, lw=1.2, ls="--", label=f"Saturation (no new codes for {SATURATION_RUN} participants)")
ax.set_xlabel("Participant (order of participation)")
ax.set_ylabel("Number of interview codes")
ax.set_xticks(S["order"])
ax.legend(frameon=False, loc="center right")
ax.set_title("New and total interview codes", loc="left", color=INK)
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
