#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys
ROOT=Path(__file__).resolve().parent
tests=[
    ROOT/"tests"/"test_handoff_pack.py",
    ROOT/"previous_v4"/"test_stage04_v4.py",
]
failed=False
for test in tests:
    result=subprocess.run([sys.executable,str(test)])
    print(f"{test.name}: {'PASS' if result.returncode==0 else 'FAIL'}")
    failed |= result.returncode != 0
raise SystemExit(1 if failed else 0)
