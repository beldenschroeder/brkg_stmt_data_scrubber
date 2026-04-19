"""Unit tests for model serialization."""

from brkg_stmt_data_scrubber.models import CSV_COLUMNS, Transaction


def test_csv_columns_order():
    """The CSV column order is part of the public contract — pin it down."""
    assert CSV_COLUMNS == [
        "Date",
        "Description",
        "Account",
        "Statement Ending",
        "Month Ending",
        "Debit",
        "Credit",
    ]


def test_to_row_handles_credit_only():
    txn = Transaction(date="2026-01-01", description="x", account="Dividends", credit=10.5)
    assert txn.to_row() == ["2026-01-01", "x", "Dividends", "", "", "", "10.50"]


def test_to_row_handles_debit_only():
    txn = Transaction(date="2026-01-01", description="x", account="N/A", debit=200.0)
    assert txn.to_row() == ["2026-01-01", "x", "N/A", "", "", "200.00", ""]


def test_to_row_handles_all_empty():
    assert Transaction().to_row() == ["", "", "", "", "", "", ""]


def test_to_row_with_statement_ending_and_month_ending():
    txn = Transaction(
        date="2026-03-02",
        description="HTSXX",
        account="Dividends",
        statement_ending="2026-03-31",
        month_ending="2026-03-31",
        credit=12.20,
    )
    assert txn.to_row() == [
        "2026-03-02",
        "HTSXX",
        "Dividends",
        "2026-03-31",
        "2026-03-31",
        "",
        "12.20",
    ]


def test_to_row_negative_credit_uses_minus_sign():
    """Negative credits export as -25.00 (Excel-friendly), NOT (25.00) accounting form."""
    txn = Transaction(date="2026-01-01", description="reversal", account="Adjustment", credit=-25.0)
    assert txn.to_row()[6] == "-25.00"


def test_to_row_large_number_has_no_thousands_separator():
    """Large numbers must be plain (10062.00) — no commas, so Excel reads as Number."""
    txn = Transaction(date="2026-03-30", description="VZ (buy)", account="N/A", debit=10062.00)
    assert txn.to_row()[5] == "10062.00"
