from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]

def test_hft_config():
    text=(ROOT/"config"/"hft_data.py").read_text(encoding="utf-8")
    tree=ast.parse(text)
    names={n.targets[0].id for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
    assert "HFT_RESOLUTION" in names and "HFT_STRIKE_OFFSETS" in names
def test_scripts_exist():
    for name in ("discover_fyers_10s_retention.py","build_hft_10s_manifest.py",
                 "download_hft_10s_data.py","validate_hft_10s_coverage.py"):
        assert (ROOT/"scripts"/name).exists()
def test_requested_ladder_is_12():
    text=(ROOT/"config"/"hft_data.py").read_text(encoding="utf-8")
    assert 'HFT_RESOLUTION = "10S"' in text
    assert 'HFT_FETCH_RESOLUTION = "5S"' in text
    assert 'HFT_UNDERLYING_MODE = "NIFTY_FUTURES"' in text
    assert "(0, 50, 100, 150, 200, 250)" in text
    assert '("CE", "PE")' in text
