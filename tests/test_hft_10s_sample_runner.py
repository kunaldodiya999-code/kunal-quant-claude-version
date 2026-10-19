from pathlib import Path

def test_sample_runner_exists():
    assert Path("scripts/run_hft_10s_sample.py").exists()
