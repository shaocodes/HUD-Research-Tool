"""
make_practice_clips.py
----------------------
Builds two short PRACTICE gameplay clips for learning to tag in the coding
app, plus a reference answer key of when each event really happens.

The clips are a simple top-down mock game (not GTA V or Cyberpunk footage):
a player marker drives through a city grid toward an objective. Clip 1 uses
a full HUD (mini-map, waypoint, quest text, health); clip 2 a minimal HUD
(health and prompts only). Each clip contains every event type the study
codes, one static stretch and one loading screen to mark as skipped.

Outputs
  practice/practice_full.mp4, practice/practice_minimal.mp4
  practice/reference_events.csv, practice/reference_exclusions.csv

Run:  python scripts/make_practice_clips.py
"""
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "practice"
OUT.mkdir(exist_ok=True)

W, H, FPS = 640, 360, 15
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
f_small, f_med, f_big = (ImageFont.truetype(FONT, 12), ImageFont.truetype(FONT, 15),
                         ImageFont.truetype(FONT_B, 22))
BLOCK = 90  # city block size in world pixels

# Each clip: list of (start_s, end_s, action, extra)
#   drive  : move along heading;  turn  : change heading at start
#   idle   : no movement (hesitation); map: full-screen map overlay
#   menu   : inventory overlay;  loading: black loading screen
#   prompt : interaction prompt shown (player ignores it -> missed prompt)
#   wrong  : wrong turn then turn back;  misfire: weapon wheel flashes (unintended input)
#   obj_new / obj_done : objective banners
SCRIPTS = {
    "full": [
        (0, 3, "obj_new", "Reach the garage"), (0, 22, "drive", 0),
        (22, 22, "turn", 90), (22, 30, "drive", 0),
        (30, 34, "map", None),
        (34, 52, "drive", 0), (40, 43, "prompt", "Press E to talk"),
        (52, 55, "idle", None),
        (55, 55, "turn", 0), (55, 63, "drive", 0),
        (63, 66, "misfire", None),
        (66, 92, "drive", 0),                       # long straight drive (static stretch 68-90)
        (92, 95, "obj_done", None),
        (95, 105, "loading", None),                 # loading screen
        (105, 108, "obj_new", "Meet the contact"), (105, 120, "drive", 0),
        (120, 125, "menu", None),
        (125, 125, "turn", 90), (125, 140, "drive", 0),
        (140, 143, "obj_done", None),
    ],
    "minimal": [
        (0, 3, "obj_new", "Reach the garage"), (0, 16, "drive", 0),
        (16, 21, "idle", None),
        (21, 24, "map", None),
        (24, 24, "turn", 90), (24, 36, "drive", 0),
        (36, 44, "wrong", None),
        (44, 49, "map", None),
        (49, 49, "turn", 0), (49, 60, "drive", 0), (52, 55, "prompt", "Press E to open"),
        (60, 64, "idle", None),
        (64, 90, "drive", 0),                       # static stretch 66-88
        (90, 93, "obj_done", None),
        (93, 103, "loading", None),
        (103, 106, "obj_new", "Meet the contact"), (103, 118, "drive", 0),
        (118, 121, "misfire", None),
        (121, 126, "map", None),
        (126, 126, "turn", 90), (126, 142, "drive", 0),
        (142, 145, "obj_done", None),
    ],
}
DURATION = {"full": 146, "minimal": 148}

# What a careful coder should log (onset times) -> reference answer key
EVENT_OF = {"map": "full_map_open", "idle": "hesitation", "prompt": "missed_prompt",
            "wrong": "navigation_error", "misfire": "unintended_action", "menu": "menu_break",
            "obj_new": "objective_received", "obj_done": "objective_reached"}
SKIPS = {"full": [(68, 90, "static"), (95, 105, "no_gameplay")],
         "minimal": [(66, 88, "static"), (93, 103, "no_gameplay")]}


def active(script, t, kind):
    return [s for s in script if s[2] == kind and s[0] <= t < max(s[1], s[0] + 1e-9)]


def render(hud):
    script = SCRIPTS[hud]
    dur = DURATION[hud]
    rng = np.random.default_rng(7 if hud == "full" else 8)
    # precompute player path
    pos = np.array([BLOCK * 3.5, BLOCK * 3.0])
    heading = 0.0  # degrees, 0 = up
    speed = 55.0
    frames = int(dur * FPS)
    path = []
    turned = set()
    for i in range(frames):
        t = i / FPS
        for s in script:
            if s[2] == "turn" and s[0] <= t and s not in turned:
                heading = (heading + s[3]) % 360
                turned.add(s)
        moving = bool(active(script, t, "drive")) and not active(script, t, "idle") \
            and not active(script, t, "map") and not active(script, t, "menu") and not active(script, t, "loading")
        wrong = active(script, t, "wrong")
        h = heading
        if wrong:
            s0, s1 = wrong[0][0], wrong[0][1]
            h = heading + (90 if t < (s0 + s1) / 2 else 270)
            moving = True
        if moving:
            rad = np.radians(h)
            pos = pos + speed / FPS * np.array([np.sin(rad), -np.cos(rad)])
        path.append((pos.copy(), h))

    target = path[-1][0] + np.array([BLOCK * 1.5, -BLOCK * 1.0])
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT / f"practice_{hud}.mp4")],
        stdin=subprocess.PIPE)

    for i in range(frames):
        t = i / FPS
        (px, py), h = path[i]
        img = Image.new("RGB", (W, H), (34, 38, 46))
        d = ImageDraw.Draw(img)
        if active(script, t, "loading"):
            img = Image.new("RGB", (W, H), (5, 5, 8))
            d = ImageDraw.Draw(img)
            dots = "." * (int(t * 2) % 4)
            d.text((W / 2 - 50, H / 2 - 12), "LOADING" + dots, font=f_big, fill=(200, 200, 200))
        else:
            ox, oy = px - W / 2, py - H / 2
            # city blocks
            x0 = int(np.floor(ox / BLOCK)) * BLOCK
            y0 = int(np.floor(oy / BLOCK)) * BLOCK
            for bx in range(x0, int(ox + W) + BLOCK, BLOCK):
                for by in range(y0, int(oy + H) + BLOCK, BLOCK):
                    shade = 52 + int((hash((bx, by)) % 5) * 6)
                    d.rectangle([bx - ox + 14, by - oy + 14, bx - ox + BLOCK - 14, by - oy + BLOCK - 14],
                                fill=(shade, shade + 4, shade + 10))
            # player
            rad = np.radians(h)
            cx, cy = W / 2, H / 2
            pts = [(cx + 11 * np.sin(rad), cy - 11 * np.cos(rad)),
                   (cx + 7 * np.sin(rad + 2.4), cy - 7 * np.cos(rad + 2.4)),
                   (cx + 7 * np.sin(rad - 2.4), cy - 7 * np.cos(rad - 2.4))]
            d.polygon(pts, fill=(255, 210, 80))
            # HUD
            d.rectangle([12, 12, 132, 22], outline=(220, 220, 220))
            hp = 0.85 if t < 60 else 0.55
            d.rectangle([13, 13, 13 + 118 * hp, 21], fill=(210, 70, 70))
            if hud == "full":
                tx, ty = target - np.array([ox, oy])
                ang = np.arctan2(ty - cy, tx - cx)
                mx = np.clip(tx, 20, W - 20) if 0 <= tx <= W else cx + 140 * np.cos(ang)
                my = np.clip(ty, 20, H - 20) if 0 <= ty <= H else cy + 140 * np.sin(ang)
                d.polygon([(mx, my - 8), (mx + 6, my), (mx, my + 8), (mx - 6, my)], fill=(90, 200, 255))
                # mini-map
                d.rectangle([12, H - 112, 112, H - 12], fill=(20, 24, 30), outline=(200, 200, 200))
                for k in range(-3, 4):
                    d.line([12, H - 62 + k * 15 - (py / 6 % 15), 112, H - 62 + k * 15 - (py / 6 % 15)], fill=(55, 60, 70))
                    d.line([62 + k * 15 - (px / 6 % 15), H - 112, 62 + k * 15 - (px / 6 % 15), H - 12], fill=(55, 60, 70))
                d.ellipse([58, H - 66, 66, H - 58], fill=(255, 210, 80))
                vx, vy = (target - np.array([px, py])) / 6
                ex, ey = np.clip(62 + vx, 16, 108), np.clip(H - 62 + vy, H - 108, H - 16)
                d.line([62, H - 62, ex, ey], fill=(90, 200, 255), width=2)
                quest = [s[3] for s in script if s[2] == "obj_new" and s[0] <= t]
                if quest:
                    d.text((W - 190, 14), "◆ " + quest[-1], font=f_small, fill=(230, 230, 230))
            for s in active(script, t, "prompt"):
                d.rectangle([W / 2 - 80, H - 60, W / 2 + 80, H - 36], fill=(0, 0, 0), outline=(240, 240, 240))
                d.text((W / 2 - 68, H - 56), s[3], font=f_med, fill=(255, 255, 255))
            if active(script, t, "misfire"):
                d.ellipse([W / 2 - 70, H / 2 - 70, W / 2 + 70, H / 2 + 70], outline=(240, 240, 240), width=3)
                d.text((W / 2 - 52, H / 2 - 9), "WEAPON WHEEL", font=f_small, fill=(240, 240, 240))
            if active(script, t, "map"):
                d.rectangle([40, 30, W - 40, H - 30], fill=(18, 22, 28), outline=(220, 220, 220))
                d.text((56, 40), "MAP", font=f_big, fill=(230, 230, 230))
                for k in range(8):
                    d.line([60, 80 + k * 30, W - 60, 80 + k * 30], fill=(60, 66, 76))
                    d.line([90 + k * 65, 75, 90 + k * 65, H - 45], fill=(60, 66, 76))
                d.ellipse([W / 2 - 5, H / 2 - 5, W / 2 + 5, H / 2 + 5], fill=(255, 210, 80))
                d.polygon([(W / 2 + 120, H / 2 - 60), (W / 2 + 128, H / 2 - 52), (W / 2 + 120, H / 2 - 44),
                           (W / 2 + 112, H / 2 - 52)], fill=(90, 200, 255))
            if active(script, t, "menu"):
                d.rectangle([0, 0, W, H], fill=(10, 10, 14))
                d.text((40, 30), "INVENTORY", font=f_big, fill=(230, 230, 230))
                for k in range(6):
                    d.rectangle([40 + k * 92, 90, 120 + k * 92, 170], outline=(120, 120, 130))
            for s in active(script, t, "obj_new"):
                d.rectangle([W / 2 - 150, 40, W / 2 + 150, 70], fill=(0, 0, 0))
                d.text((W / 2 - 140, 46), "NEW OBJECTIVE: " + s[3], font=f_med, fill=(255, 220, 120))
            if active(script, t, "obj_done"):
                d.rectangle([W / 2 - 110, 40, W / 2 + 110, 70], fill=(0, 0, 0))
                d.text((W / 2 - 98, 46), "OBJECTIVE COMPLETE", font=f_med, fill=(140, 230, 140))
        # clip label + clock (helps coders check timestamps)
        d.text((W - 92, H - 20), f"{int(t // 60):02d}:{int(t % 60):02d}", font=f_small, fill=(170, 170, 170))
        d.text((W - 260, H - 20), f"PRACTICE · {hud.upper()} HUD", font=f_small, fill=(120, 120, 130))
        proc.stdin.write(np.asarray(img, dtype=np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()


ref_events, ref_skips = [], []
for hud in ("full", "minimal"):
    render(hud)
    for s in SCRIPTS[hud]:
        if s[2] in EVENT_OF:
            ref_events.append({"clip": f"practice_{hud}", "t_s": float(s[0]), "event": EVENT_OF[s[2]]})
    for a, b, why in SKIPS[hud]:
        ref_skips.append({"clip": f"practice_{hud}", "start_s": a, "end_s": b, "reason": why})
pd.DataFrame(ref_events).sort_values(["clip", "t_s"]).to_csv(OUT / "reference_events.csv", index=False)
pd.DataFrame(ref_skips).to_csv(OUT / "reference_exclusions.csv", index=False)
for f in sorted(OUT.glob("*")):
    print(f.name, f.stat().st_size)
