# Test suite fixes

Two real bugs found while running `tests/` against the canonical repo on
2026-09-27 (see the session checkpoint). Both are fixed here and verified
— not applied to `KunalQuant`.

## 1. `tests/ktmi_fyers_validation_test.py` — 5 tests errored, not failed

All 5 test functions take a `bars` parameter, which pytest treats as a
request for a fixture named `bars`. `load_fyers_bars()` is defined in the
same file and clearly meant to supply it, but it was never decorated with
`@pytest.fixture` — so pytest had no fixture named `bars` to find at all.

**Fix:** add, right after `load_fyers_bars()` is defined:

```python
@pytest.fixture
def bars() -> list[OHLCData]:
    return load_fyers_bars()
```

(plus `import pytest` near the top). That's the entire change — nothing
about `load_fyers_bars()` itself, or any KTMI logic, is touched.

**Verified:** `ktmi_fyers_validation_test.py` here is the patched file.
`conftest.py` mocks `load_fyers_bars()` with synthetic OHLC data (since
the real database isn't available in this environment) purely so the fix
can be exercised. Result:

```
$ PYTHONPATH=<KunalQuant checkout> python3 -m pytest ktmi_fyers_validation_test.py -q
.....                                                                    [100%]
5 passed in 0.09s
```

**Running it against real data (2026-09-28 update):** the first real-data
attempt on your machine got past the old `fixture 'bars' not found` error
(so the wiring fix works there too) but then failed with
`Database not found`, because the original file finds the database via
`Path(__file__).parents[1]` — correct inside `tests/`, wrong in this
copy. This copy now takes the root from `config.settings.PROJECT_ROOT`
instead, so it works from any location as long as `PYTHONPATH` points at
the KunalQuant repo. The change to the file *in the canonical repo* is
still only the 3-line fixture addition.

This proves the *fixture wiring* is fixed. It says nothing about whether
the KTMI output matches a reference — that needs the real database, which
this environment doesn't have.

## 2. `tests/expiry_isolation_test.py` — breaks pytest collection entirely

This file isn't a test at all — no `def test_*`, no assertions, no
`import pytest`. It's a standalone diagnostic that queries `gex_snapshots`
and `option_analytics` directly at **module level** and prints JSON. It
only breaks things because its filename happens to match pytest's default
`*_test.py` discovery pattern, so pytest tries to *import* it while
collecting the suite — and that import runs the module-level queries
immediately, which fail without the real database. When that happens,
pytest aborts collection for the whole run (`pytest tests/` stops dead,
not just this one file).

**Fix:** rename it out of the `test_*.py` / `*_test.py` pattern — e.g.
`scripts/check_expiry_isolation.py` — since it was never meant to be
collected as a test. No logic changes.

**Verified:** built a throwaway `tests/` directory containing only a
renamed copy of this file (`check_expiry_isolation.py`, included here)
plus one trivial real test:

```
$ python3 -m pytest tests/ -q
.                                                                        [100%]
1 passed in 0.00s
```

Collection succeeds and the renamed file is correctly ignored. With the
original name in place, the same setup reproduces the original collection
error.

## Net effect if both are applied to the canonical repo

`pytest tests/` would go from **76 passed / 5 errors / 1 collection
failure** to (in an environment with the real database) **81 passed, 0
errors, 0 collection failures** — assuming the KTMI values themselves
check out against real data, which nothing here claims to have verified.
