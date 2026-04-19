"""Unit tests for the CSV writer."""

import csv
from pathlib import Path

import pytest

from brkg_stmt_data_scrubber.config import Config
from brkg_stmt_data_scrubber.models import (
    BROKERAGE_ACCOUNT,
    CSV_COLUMNS,
    RETIREMENT_BROKERAGE_ACCOUNT,
    AccountSection,
    Transaction,
)
from brkg_stmt_data_scrubber.writer import write_account_csv


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        input_pdf=None,
        output_dir=tmp_path,
        brokerage_csv_name="brokerage_income",
        retirement_brokerage_csv_name="retirement_brokerage_income",
        log_level="INFO",
    )


def test_writes_header_only_for_empty_section(tmp_path: Path, cfg: Config):
    section = AccountSection(account_name=BROKERAGE_ACCOUNT, transactions=[])
    out_path = write_account_csv(section, tmp_path, cfg)

    assert out_path.exists()
    assert out_path.name == "brokerage_income.csv"

    with out_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows == [CSV_COLUMNS]


def test_writes_transactions_with_correct_columns(tmp_path: Path, cfg: Config):
    section = AccountSection(
        account_name=BROKERAGE_ACCOUNT,
        transactions=[
            Transaction(
                date="2026-03-02",
                description="HTSXX",
                account="Dividends",
                statement_ending="2026-03-31",
                month_ending="2026-03-31",
                credit=12.20,
            ),
            Transaction(
                date="2026-03-30",
                description="VZ (buy)",
                account="N/A",
                statement_ending="2026-03-31",
                month_ending="2026-03-31",
                debit=10062.00,
            ),
        ],
    )
    out_path = write_account_csv(section, tmp_path, cfg)
    with out_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    assert rows[0] == CSV_COLUMNS
    assert rows[1] == ["2026-03-02", "HTSXX", "Dividends", "2026-03-31", "2026-03-31", "", "12.20"]
    assert rows[2] == ["2026-03-30", "VZ (buy)", "N/A", "2026-03-31", "2026-03-31", "10062.00", ""]


def test_csv_uses_utf8_bom_for_excel(tmp_path: Path, cfg: Config):
    """Excel on Windows uses the BOM to auto-detect UTF-8 encoding."""
    section = AccountSection(account_name=BROKERAGE_ACCOUNT, transactions=[])
    out_path = write_account_csv(section, tmp_path, cfg)
    raw_bytes = out_path.read_bytes()
    # UTF-8 BOM is EF BB BF
    assert raw_bytes.startswith(b"\xef\xbb\xbf"), "CSV should start with a UTF-8 BOM"


def test_numbers_are_unquoted_for_excel(tmp_path: Path, cfg: Config):
    """Numbers must be written without quotes so Excel reads them as Number type."""
    section = AccountSection(
        account_name=BROKERAGE_ACCOUNT,
        transactions=[
            Transaction(
                date="2026-03-02",
                description="x",
                account="Dividends",
                statement_ending="2026-03-31",
                month_ending="2026-03-31",
                credit=12.20,
            )
        ],
    )
    out_path = write_account_csv(section, tmp_path, cfg)
    raw_text = out_path.read_text(encoding="utf-8-sig")
    # Look for the bare number (not "12.20" with quotes)
    assert ",12.20" in raw_text or raw_text.endswith("12.20\r\n") or raw_text.endswith("12.20\n")
    assert ',"12.20"' not in raw_text


def test_dates_are_unquoted_iso_for_excel(tmp_path: Path, cfg: Config):
    """ISO dates must be unquoted so Excel reads them as Date type."""
    section = AccountSection(
        account_name=BROKERAGE_ACCOUNT,
        transactions=[
            Transaction(
                date="2026-03-02",
                description="x",
                account="Dividends",
                statement_ending="2026-03-31",
                month_ending="2026-03-31",
                credit=1.0,
            )
        ],
    )
    out_path = write_account_csv(section, tmp_path, cfg)
    raw_text = out_path.read_text(encoding="utf-8-sig")
    assert "2026-03-02," in raw_text
    assert ',"2026-03-02"' not in raw_text


def test_uses_retirement_filename_for_retirement_section(tmp_path: Path, cfg: Config):
    section = AccountSection(account_name=RETIREMENT_BROKERAGE_ACCOUNT, transactions=[])
    out_path = write_account_csv(section, tmp_path, cfg)
    assert out_path.name == "retirement_brokerage_income.csv"


def test_creates_output_dir_if_missing(tmp_path: Path, cfg: Config):
    nested = tmp_path / "deep" / "nested" / "dir"
    section = AccountSection(account_name=BROKERAGE_ACCOUNT, transactions=[])
    out_path = write_account_csv(section, nested, cfg)
    assert out_path.exists()
    assert nested.exists()


def test_respects_custom_filenames(tmp_path: Path):
    custom_cfg = Config(
        input_pdf=None,
        output_dir=tmp_path,
        brokerage_csv_name="my_brokerage_data",
        retirement_brokerage_csv_name="my_ira_data",
        log_level="INFO",
    )
    bsec = AccountSection(account_name=BROKERAGE_ACCOUNT, transactions=[])
    rsec = AccountSection(account_name=RETIREMENT_BROKERAGE_ACCOUNT, transactions=[])
    bp = write_account_csv(bsec, tmp_path, custom_cfg)
    rp = write_account_csv(rsec, tmp_path, custom_cfg)
    assert bp.name == "my_brokerage_data.csv"
    assert rp.name == "my_ira_data.csv"


def test_negative_amount_formatted_as_minus_sign(tmp_path: Path, cfg: Config):
    section = AccountSection(
        account_name=BROKERAGE_ACCOUNT,
        transactions=[Transaction(date="2026-01-01", description="x", account="Adj", credit=-25.0)],
    )
    out_path = write_account_csv(section, tmp_path, cfg)
    with out_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[1][6] == "-25.00"
