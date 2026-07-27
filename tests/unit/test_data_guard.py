"""The data guard must block every spreadsheet except the whitelisted sample."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_spreadsheets import is_forbidden  # noqa: E402


def test_sample_fixture_is_allowed():
    assert not is_forbidden("tests/fixtures/sample_public.xlsx")


def test_stray_spreadsheets_are_blocked():
    for path in [
        "data.xlsx",
        "tests/fixtures/other.xlsx",
        "docs/real_confidential_data.xlsx",
        "notes/plan.XLSM",
        "a/b/c.xls",
        "x.ods",
        "y.xlsb",
    ]:
        assert is_forbidden(path), path


def test_non_spreadsheets_pass():
    for path in ["core/config.py", "README.md", "tests/fixtures/golden.json"]:
        assert not is_forbidden(path), path
