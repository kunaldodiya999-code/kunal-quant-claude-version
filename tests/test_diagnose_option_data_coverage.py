from pathlib import Path
import sqlite3

from scripts.diagnose_option_data_coverage import main


def test_diagnostic_module_imports():
    assert callable(main)
