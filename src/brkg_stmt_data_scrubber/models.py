"""Domain models for parsed transactions.

Output formatting is tuned for Excel auto-recognition when the CSV is opened
or imported:

  - Dates are emitted as ISO 8601 (``YYYY-MM-DD``). Excel recognizes this
    format natively as a Date type without explicit column-format settings.
  - Numbers are emitted as plain unquoted decimals (``12.20``, ``-25.00``),
    with no currency symbol and no thousands separator. Excel recognizes
    these as Number type natively.
"""

from dataclasses import dataclass, field

# CSV column order — single source of truth.
CSV_COLUMNS: list[str] = [
    "Date",
    "Description",
    "Account",
    "Statement Ending",
    "Month Ending",
    "Debit",
    "Credit",
]

# Account-section identifiers used internally and in output filenames.
BROKERAGE_ACCOUNT = "BROKERAGE"
RETIREMENT_BROKERAGE_ACCOUNT = "RETIREMENT BROKERAGE"


@dataclass
class Transaction:
    """A single parsed transaction row destined for the CSV.

    All date fields are stored as ISO 8601 strings (``YYYY-MM-DD``) so they
    flow into the CSV in a format Excel imports natively as Date type.
    """

    date: str = ""  # ISO 8601: "YYYY-MM-DD"
    description: str = ""
    account: str = ""
    statement_ending: str = ""  # ISO 8601: "YYYY-MM-DD"
    month_ending: str = ""  # ISO 8601: "YYYY-MM-DD"
    debit: float | None = None
    credit: float | None = None

    def to_row(self) -> list[str]:
        """Return values in CSV column order, formatted for Excel import."""
        return [
            self.date,
            self.description,
            self.account,
            self.statement_ending,
            self.month_ending,
            _fmt_money(self.debit),
            _fmt_money(self.credit),
        ]


@dataclass
class AccountSection:
    """All parsed transactions from a single account's relevant sections."""

    account_name: str
    transactions: list[Transaction] = field(default_factory=list)


def _fmt_money(value: float | None) -> str:
    """Format a money value for Excel-friendly CSV output.

    - ``None`` becomes the empty string.
    - Numbers are 2-decimal plain floats with no currency symbol and no
      thousands separator (e.g. ``"12.20"``, ``"-25.00"``, ``"10062.00"``).
      Excel recognizes this format as a Number.
    """
    if value is None:
        return ""
    return f"{value:.2f}"
