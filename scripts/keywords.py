"""
keywords.py — step 4: keyword support for thematic analysis
-----------------------------------------------------------
Input : clean/interview_answers.csv (from clean_transcripts.py)

Keeps only the words that carry meaning, then compares them between HUD
conditions. It SUPPORTS the manual coding; it does not replace it.

  1. lower-case, split into words, drop anonymisation tokens ([name] ...)
  2. remove common words (the, and, I, was ...) BUT keep negations
     (no, not, never, didn't, don't, nothing ...), so "didn't feel lost"
     keeps its meaning; "not" is joined to the next word ("not_sure")
  3. merge simple word forms (maps -> map, buildings -> building)
  4. count each word per HUD condition and per question
  5. rank the words most typical of each condition (log-odds with a small prior)

Outputs
  results/K_keywords_by_condition.csv   word, count full, count minimal, log-odds
  results/K_keywords_by_question.csv    top words per question and condition
  figures/fig_keywords.png

Run:  python scripts/keywords.py
"""
from pathlib import Path
import re
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN, RES, FIG = ROOT / "clean", ROOT / "results", ROOT / "figures"
RES.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

NEGATIONS = {"no", "not", "never", "nothing", "none", "nobody", "didn't", "don't", "doesn't", "wasn't",
             "couldn't", "can't", "won't", "isn't", "weren't", "without"}
STOPWORDS = set("""a about above after again all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her
here hers him his how i i'm i've if in into is it it's its itself just kind kinda let's like me more most my myself
of off on once only or other our out over own really same she should so some such than that that's the their them
then there these they this those through to too under until up us very was we were what when where which while who
whom why will with would you your yours yeah okay ok also got get went go going one thing things stuff lot much
said say think time times way well even still back around""".split())
TOKEN = re.compile(r"\[[a-z]+\]|[a-z]+(?:'[a-z]+)?")


def lemma(w):
    if w in NEGATIONS or len(w) < 4:
        return w
    for suf, rep in (("ies", "y"), ("sses", "ss"), ("s", "")):
        if w.endswith(suf) and not w.endswith("ss"):
            return w[: -len(suf)] + rep
    return w


def keywords(text):
    out = []
    for sentence in re.split(r"[.!?;,]", str(text).lower()):   # negation never crosses a clause
        toks = [t for t in TOKEN.findall(sentence) if not t.startswith("[")]
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in NEGATIONS:
                # join with the next content word within 3 words: "not really sure" -> not_sure
                j = next((k for k in range(i + 1, min(i + 4, len(toks)))
                          if toks[k] not in STOPWORDS and toks[k] not in NEGATIONS), None)
                if j is not None:
                    out.append(f"not_{lemma(toks[j])}")
                    i = j + 1
                    continue
            elif t not in STOPWORDS and len(t) > 2:
                out.append(lemma(t))
            i += 1
    return out


ans = pd.read_csv(CLEAN / "interview_answers.csv")
ans["keywords"] = ans["answer"].map(keywords)
ans[["participant", "session", "hud", "question", "answer"]].assign(
    keywords=ans["keywords"].map(" ".join)).to_csv(CLEAN / "interview_keywords.csv", index=False)

per_q = ans[ans["question"].isin([f"Q{i}" for i in range(1, 9)])]
cnt = {h: Counter(w for ws in per_q.loc[per_q["hud"] == h, "keywords"] for w in ws) for h in ("full", "minimal")}
vocab = set(cnt["full"]) | set(cnt["minimal"])
nf, nm = sum(cnt["full"].values()), sum(cnt["minimal"].values())
a0 = 0.5                                                   # small prior so rare words don't dominate
rows = []
for w in vocab:
    f, m = cnt["full"][w], cnt["minimal"][w]
    lo = np.log((m + a0) / (nm + a0 * len(vocab) - m - a0)) - np.log((f + a0) / (nf + a0 * len(vocab) - f - a0))
    rows.append({"word": w, "full": f, "minimal": m, "total": f + m, "log_odds_minimal_vs_full": lo})
kw = pd.DataFrame(rows).query("total >= 3").sort_values("log_odds_minimal_vs_full")
kw.round(3).to_csv(RES / "K_keywords_by_condition.csv", index=False)

top = []
for (q, h), g in per_q.groupby(["question", "hud"]):
    c = Counter(w for ws in g["keywords"] for w in ws)
    for rank, (w, n) in enumerate(c.most_common(5), start=1):
        top.append({"question": q, "hud": h, "rank": rank, "word": w, "count": n})
pd.DataFrame(top).to_csv(RES / "K_keywords_by_question.csv", index=False)

# figure: 8 words most typical of each condition
show = pd.concat([kw.head(8), kw.tail(8)])
fig, ax = plt.subplots(figsize=(3.6, 3.4))
colors = ["#2a78d6" if v < 0 else "#eb6834" for v in show["log_odds_minimal_vs_full"]]
ax.barh(range(len(show)), show["log_odds_minimal_vs_full"], color=colors, height=.65)
ax.set_yticks(range(len(show)), show["word"].str.replace("not_", "not "), fontsize=8)
ax.axvline(0, color="#52514e", lw=.8)
ax.set_xlabel("← more after full HUD    more after minimal HUD →", fontsize=8, color="#52514e")
ax.set_title("Words most typical of each condition", fontsize=9.5, loc="left", color="#0b0b0b")
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
ax.tick_params(colors="#52514e", labelsize=8)
fig.tight_layout()
fig.savefig(FIG / "fig_keywords.png", dpi=300)
plt.close(fig)
print(f"keywords.py: {len(vocab)} distinct words; most typical of minimal: {', '.join(kw.tail(5)['word'][::-1])}; "
      f"of full: {', '.join(kw.head(5)['word'])}")
