"""
gaze.py — step 3: webcam eye tracking
-------------------------------------
Input : raw/gaze/<P>_S<n>.csv   samples: t_s, x, y (0-1, origin top-left), confidence
        raw/aoi_regions.csv     screen box of each HUD element per game and HUD condition
        clean/skipped_segments.csv, clean/session_metrics.csv  (from clean.py)

Cleaning, per sample
  1. blinks / lost tracking  - x or y missing          -> removed
  2. low confidence          - confidence < 0.6        -> removed
  3. off screen              - x or y outside 0-1      -> removed
  4. skipped footage         - inside a skipped segment -> removed
A session whose remaining samples are < 60 % of its active samples is left out
of the gaze analysis (other measures kept).

Then each sample is assigned to the AOI box it falls in, or "Game world".
Outputs
  clean/gaze_aoi.csv          share of gaze time per AOI per session
  clean/gaze_grid.csv         binned gaze density per game x HUD (for heatmaps)
  clean/gaze_cleaning_log.csv samples removed per reason per session
  figures/fig_gaze_heatmaps.png
  and adds gaze_* columns to clean/session_metrics.csv

Run:  python scripts/gaze.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parent.parent
RAW, CLEAN, FIG = ROOT / "raw", ROOT / "clean", ROOT / "figures"
FIG.mkdir(exist_ok=True)

MIN_CONFIDENCE = 0.6
MIN_VALID_SHARE = 0.60
GRID_X, GRID_Y = 32, 18           # heatmap bins (16:9 screen)

aoi = pd.read_csv(RAW / "aoi_regions.csv")
skips = pd.read_csv(CLEAN / "skipped_segments.csv")
metrics = pd.read_csv(CLEAN / "session_metrics.csv")
log_path = CLEAN / "cleaning_log.csv"
main_log = pd.read_csv(log_path)

shares, glog, grids = [], [], {}
for r in metrics.itertuples():
    f = RAW / "gaze" / f"{r.participant}_S{r.session}.csv"
    if not f.exists():
        glog.append({"participant": r.participant, "session": r.session, "note": "no gaze file"})
        continue
    g = pd.read_csv(f)
    n_all = len(g)
    seg = skips[(skips["participant"] == r.participant) & (skips["session"] == r.session)]
    in_skip = np.zeros(n_all, dtype=bool)
    for a, b in zip(seg["start_s"], seg["end_s"]):
        in_skip |= (g["t_s"] >= a) & (g["t_s"] <= b)
    g = g[~in_skip]
    n_active = len(g)
    blink = g["x"].isna() | g["y"].isna()
    low = ~blink & (g["confidence"] < MIN_CONFIDENCE)
    off = ~blink & ~low & ((g["x"] < 0) | (g["x"] > 1) | (g["y"] < 0) | (g["y"] > 1))
    g = g[~(blink | low | off)]
    valid_share = len(g) / n_active if n_active else 0
    ok = valid_share >= MIN_VALID_SHARE
    glog.append({"participant": r.participant, "session": r.session, "samples": n_all,
                 "removed_skipped": int(in_skip.sum()), "removed_blink": int(blink.sum()),
                 "removed_low_confidence": int(low.sum()), "removed_off_screen": int(off.sum()),
                 "valid_share": round(valid_share, 3), "used": ok})
    if not ok:
        main_log.loc[len(main_log)] = ["gaze", f"{r.participant} S{r.session}",
                                       f"only {valid_share:.0%} of samples usable (low confidence)",
                                       "gaze left out for this session; other measures kept"]
        continue
    boxes = aoi[(aoi["game"] == r.game) & (aoi["hud"] == r.hud)]
    label = np.full(len(g), "Game world", dtype=object)
    for b in boxes.itertuples():
        inside = (g["x"] >= b.x0) & (g["x"] <= b.x1) & (g["y"] >= b.y0) & (g["y"] <= b.y1)
        label[inside.values & (label == "Game world")] = b.aoi
    vc = pd.Series(label).value_counts(normalize=True)
    for name, share in vc.items():
        shares.append({"participant": r.participant, "session": r.session, "game": r.game, "hud": r.hud,
                       "aoi": name, "share": share})
    h, _, _ = np.histogram2d(g["y"], g["x"], bins=[GRID_Y, GRID_X], range=[[0, 1], [0, 1]])
    grids.setdefault((r.game, r.hud), []).append(h / h.sum())

sh = pd.DataFrame(shares)
sh.to_csv(CLEAN / "gaze_aoi.csv", index=False)
pd.DataFrame(glog).to_csv(CLEAN / "gaze_cleaning_log.csv", index=False)
gl = pd.DataFrame(glog)
main_log.loc[len(main_log)] = ["gaze", "all sessions",
                               f"{gl['removed_blink'].sum():,} blink, {gl['removed_low_confidence'].sum():,} low-confidence and "
                               f"{gl['removed_off_screen'].sum():,} off-screen samples", "removed before assigning areas of interest"]
main_log.to_csv(log_path, index=False)

wide = sh.pivot_table(index=["participant", "session"], columns="aoi", values="share", fill_value=0)
wide.columns = ["gaze_" + c.lower().replace(" ", "_").replace("-", "_") for c in wide.columns]
wide["gaze_hud_total"] = 1 - wide["gaze_game_world"]
metrics = metrics.drop(columns=[c for c in metrics.columns if c.startswith("gaze_")]).merge(
    wide.reset_index(), on=["participant", "session"], how="left")
metrics.round(4).to_csv(CLEAN / "session_metrics.csv", index=False)

# heatmap grid (mean density across sessions) + figure
rows = []
for (game, hud), hs in grids.items():
    mean = gaussian_filter(np.mean(hs, axis=0), 0.8)
    mean = mean / mean.sum()
    for iy in range(GRID_Y):
        for ix in range(GRID_X):
            rows.append({"game": game, "hud": hud, "gx": ix, "gy": iy, "density": mean[iy, ix],
                         "sessions": len(hs)})
grid = pd.DataFrame(rows)
grid.to_csv(CLEAN / "gaze_grid.csv", index=False)

fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.4))
for ax, (game, hud) in zip(axes.flat, [("GTA V", "full"), ("GTA V", "minimal"),
                                       ("Cyberpunk 2077", "full"), ("Cyberpunk 2077", "minimal")]):
    sub = grid[(grid["game"] == game) & (grid["hud"] == hud)]
    if sub.empty:
        ax.axis("off")
        continue
    img = sub.pivot(index="gy", columns="gx", values="density").values
    ax.imshow(img, extent=[0, 1, 1, 0], cmap="Blues", interpolation="bilinear", aspect="auto",
              vmin=0, vmax=grid["density"].quantile(.995))
    for b in aoi[(aoi["game"] == game) & (aoi["hud"] == hud)].itertuples():
        ax.add_patch(Rectangle((b.x0, b.y0), b.x1 - b.x0, b.y1 - b.y0, fill=False, lw=1, ec="#eb6834"))
        if b.x1 - b.x0 > .25:                     # wide box: label above it
            ax.text((b.x0 + b.x1) / 2, b.y0 - .015, b.aoi, fontsize=6.5, color="#52514e", va="bottom", ha="center")
            continue
        left_side = (b.x0 + b.x1) / 2 < .5        # label beside the box, on the side facing the centre
        ax.text(b.x1 + .012 if left_side else b.x0 - .012, (b.y0 + b.y1) / 2, b.aoi, fontsize=6.5,
                color="#52514e", va="center", ha="left" if left_side else "right")
    ax.set_title(f"{game} · {hud} HUD  (n = {sub['sessions'].iloc[0]})", fontsize=8.5, loc="left", color="#0b0b0b")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#e4e3df")
fig.tight_layout()
fig.savefig(FIG / "fig_gaze_heatmaps.png", dpi=300)
plt.close(fig)
print(f"gaze.py: {int(gl['used'].sum())}/{len(gl)} sessions used; heatmaps -> figures/fig_gaze_heatmaps.png")
