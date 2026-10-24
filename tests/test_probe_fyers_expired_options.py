def test_expired_option_api_probe_imports():
    from scripts.probe_fyers_expired_options import main
    assert callable(main)
