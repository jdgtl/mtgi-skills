import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
ENRICH = SKILL_ROOT / "scripts" / "enrich_mpn.py"


def _run_batch(tmp_path, mpns, **env):
    inputs = tmp_path / "in.json"
    inputs.write_text(json.dumps([{"mpn": m, "need": []} for m in mpns]))
    out = tmp_path / "out.jsonl"
    cmd = [
        sys.executable, str(ENRICH),
        "--batch", str(inputs),
        "--results-jsonl", str(out),
        "--no-cache",
    ]
    proc_env = {**os.environ, **env, "RFQ_CACHE_DIR": str(tmp_path / "cache")}
    # Force all tiers to be skipped: don't set BROKERBIN_API_KEY / BRAVE_SEARCH_API_KEY
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        proc_env.pop(k, None)
    subprocess.run(cmd, env=proc_env, check=True, capture_output=True)
    return out


def test_batch_writes_one_jsonl_line_per_mpn(tmp_path):
    out = _run_batch(tmp_path, ["A-1", "B-2", "C-3"])
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 3
    mpns_written = {json.loads(l)["mpn"] for l in lines}
    assert mpns_written == {"A-1", "B-2", "C-3"}


def test_batch_resumes_skipping_completed_mpns(tmp_path):
    out = _run_batch(tmp_path, ["A-1", "B-2"])
    # Re-run with one extra MPN; previously-completed ones must not duplicate
    inputs2 = tmp_path / "in2.json"
    inputs2.write_text(json.dumps([
        {"mpn": "A-1", "need": []},
        {"mpn": "B-2", "need": []},
        {"mpn": "C-3", "need": []},
    ]))
    cmd = [
        sys.executable, str(ENRICH),
        "--batch", str(inputs2),
        "--results-jsonl", str(out),
        "--no-cache",
    ]
    proc_env = {**os.environ, "RFQ_CACHE_DIR": str(tmp_path / "cache")}
    for k in ("BROKERBIN_API_KEY", "BROKERBIN_LOGIN", "BRAVE_SEARCH_API_KEY",
              "MTGI_API_URL", "MTGI_API_TOKEN"):
        proc_env.pop(k, None)
    subprocess.run(cmd, env=proc_env, check=True, capture_output=True)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 3, f"expected 3 lines after resume, got {len(lines)}"
    mpns_written = [json.loads(l)["mpn"] for l in lines]
    assert mpns_written.count("A-1") == 1
    assert mpns_written.count("B-2") == 1
    assert mpns_written.count("C-3") == 1
