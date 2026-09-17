"""Portable AI-only quality gate; --full also requires the indexed main dataset."""
import argparse
import os
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--full',action='store_true');args=parser.parse_args()
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',LLM_MODE='offline',EMBEDDING_MODE='local')
command=[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--tb=short','--junitxml=data/test-results.xml']
result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,encoding='utf-8',errors='replace',timeout=180)
(ROOT/'data/test-results.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
print(result.stdout)
if result.returncode: raise SystemExit(result.returncode)
if args.full:
    result=subprocess.run([sys.executable,'-B','scripts/validate_business.py'],cwd=ROOT,env=env)
    raise SystemExit(result.returncode)
