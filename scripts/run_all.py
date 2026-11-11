"""Run the whole pipeline in order:  python scripts/run_all.py"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for step in ["clean.py", "clean_transcripts.py", "gaze.py", "keywords.py", "analyze.py"]:
    print(f"\n=== {step} ===")
    subprocess.run([sys.executable, str(HERE / step)], check=True)
