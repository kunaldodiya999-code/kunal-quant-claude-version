def test_option_candle_coverage_module_imports():
    from scripts.diagnose_option_candle_coverage import main
    assert callable(main)
