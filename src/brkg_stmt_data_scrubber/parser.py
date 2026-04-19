"""PDF parsing for JPMorgan Self-Directed Investing brokerage statements.

Statement structure (observed from real statements):

  - The PDF contains a page-footer "tab strip" on every page (STATEMENT
    SUMMARY / BROKERAGE / RETIREMENT BROKERAGE / IMPORTANT INFORMATION)
    that we MUST ignore — these are navigation, not section headers.

  - Each account's pages start with a per-page header like:
        TFR ON DEATH IND  (Acct # 744-67971)
        JPMS LLC IRA  (Acct # 956-45041)
    These reliably identify which account's data follows.

  - Income transactions live under "Income from Taxable Investments" (and
    "Income from Non-Taxable Investments" if present), inside the larger
    INCOME section of each account's Activity pages.

  - Trade transactions live under "TRADE AND INVESTMENT ACTIVITY" with
    columns: Trade Date / Settle Date / Transaction / Description / ...

  - Dates in transaction rows use the format "DD MMM YYYY"
    (e.g. "02 Mar 2026"). The CSV writer emits all dates in ISO 8601
    (YYYY-MM-DD) for native Excel Date import.

  - A single transaction spans multiple physical lines: the first line
    has the date / type / first description token / amount, and
    continuation lines carry the rest of the description plus a
    "Symbol: XXX" marker for equity-related entries.
"""

import calendar
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pdfplumber

from .models import (
    BROKERAGE_ACCOUNT,
    RETIREMENT_BROKERAGE_ACCOUNT,
    AccountSection,
    Transaction,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Date format as used in transaction rows: "02 Mar 2026"
DATE_PATTERN = re.compile(
    r"^\s*(\d{1,2}\s+" r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)" r"\s+\d{4})\b"
)

# "Statement Period Ending: March 31, 2026"  OR  "Statement Period: February 28 - March 31, 2026"
STATEMENT_END_PATTERN = re.compile(
    r"Statement Period(?:\s+Ending)?:\s*"
    r"(?:[A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?\s*[-–]\s*)?"
    r"([A-Za-z]+\s+\d{1,2},\s*\d{4})"
)

# Account markers — observed at top of each account's pages
BROKERAGE_ACCT_MARKER = re.compile(r"TFR ON DEATH IND", re.IGNORECASE)
RETIREMENT_ACCT_MARKER = re.compile(
    r"(?:JPMS\s+LLC\s+IRA|RETIREMENT\s+BROKERAGE\b)",
    re.IGNORECASE,
)

# Symbol discovery — appears on continuation lines: "Symbol: HTSXX"
SYMBOL_PATTERN = re.compile(r"Symbol:\s*([A-Z][A-Z0-9.\-]*)", re.IGNORECASE)

# Money token: optional $, digits with commas, 2 decimals,
# optionally wrapped in parens (accounting negative).
MONEY_PATTERN = re.compile(r"\(?\$?-?[\d,]+\.\d{2}\)?")

# Section / sub-section markers
INCOME_TABLE_HEADER = re.compile(
    r"^\s*Income\s+from\s+(?:Taxable|Non-Taxable)\s+Investments\b",
    re.IGNORECASE,
)
TRADE_SECTION_HEADER = re.compile(r"^\s*TRADE\s+AND\s+INVESTMENT\s+ACTIVITY\b", re.IGNORECASE)

# Markers that end an income table block
INCOME_END_MARKERS = [
    re.compile(r"^\s*Total\s+(?:Dividends|Interest|Income)\b", re.IGNORECASE),
    re.compile(r"^\s*TOTAL\s+INCOME(?:\s+FROM\b)?", re.IGNORECASE),
    re.compile(r"^\s*DEPOSITS\s+AND\s+WITHDRAWALS\b", re.IGNORECASE),
    re.compile(r"^\s*SWEEP\s+PROGRAM\s+ACTIVITY\b", re.IGNORECASE),
    re.compile(r"^\s*Total\s+Deposits\s+and\s+Withdrawals\b", re.IGNORECASE),
]

# Markers that end a trade section block
TRADE_END_MARKERS = [
    re.compile(r"^\s*Total\s+Securities\s+Bought\b", re.IGNORECASE),
    re.compile(r"^\s*TOTAL\s+TRADE\s+AND\s+INVESTMENT\b", re.IGNORECASE),
    re.compile(r"^\s*INCOME\b\s*$", re.IGNORECASE),
    re.compile(r"^\s*DEPOSITS\s+AND\s+WITHDRAWALS\b", re.IGNORECASE),
]

# Footer / navigation noise lines we always skip
NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*STATEMENT\s+SUMMARY\b.*BROKERAGE\b", re.IGNORECASE),
    re.compile(r"^\s*Please\s+read\s+the\s+important\s+disclosures", re.IGNORECASE),
    re.compile(r"^\s*See\s+additional\s+footnotes", re.IGNORECASE),
]

_TRADE_TYPE_KEYWORDS = {"BUY", "SELL", "BOUGHT", "SOLD"}


# ---------------------------------------------------------------------------
# Internal data containers
# ---------------------------------------------------------------------------


@dataclass
class _Page:
    """Lines of one PDF page, plus the statement-ending date observed on it."""

    page_num: int
    lines: list[str] = field(default_factory=list)
    statement_ending: str = ""  # ISO 'YYYY-MM-DD' if found
    account: str | None = None  # BROKERAGE / RETIREMENT BROKERAGE / None


# ---------------------------------------------------------------------------
# Parse helpers (also used by tests)
# ---------------------------------------------------------------------------


def parse_money(token: str) -> float | None:
    """Parse a money token; ``()`` indicates negative. None if unparseable."""
    if not token:
        return None
    raw = token.strip()
    if not raw:
        return None
    is_negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if is_negative else value


def extract_symbol(text: str) -> str | None:
    """Extract the ticker symbol from text containing 'Symbol: XXX'."""
    if not text:
        return None
    match = SYMBOL_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).upper()


def parse_jpm_date(text: str) -> datetime | None:
    """Parse a 'DD MMM YYYY' date (e.g. '02 Mar 2026') into a datetime."""
    try:
        return datetime.strptime(text.strip(), "%d %b %Y")
    except ValueError:
        return None


def to_iso_date(jpm_date: str) -> str:
    """Convert a 'DD MMM YYYY' date string to ISO 'YYYY-MM-DD'.

    Returns the original string if the input cannot be parsed (so we never
    silently lose data).
    """
    dt = parse_jpm_date(jpm_date)
    if dt is None:
        return jpm_date
    return dt.strftime("%Y-%m-%d")


def month_ending_for(jpm_date: str) -> str:
    """Given a 'DD MMM YYYY' string, return month-ending date 'YYYY-MM-DD'."""
    dt = parse_jpm_date(jpm_date)
    if dt is None:
        return ""
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return f"{dt.year:04d}-{dt.month:02d}-{last_day:02d}"


def normalize_statement_ending(raw: str) -> str:
    """Convert 'March 31, 2026' to ISO 'YYYY-MM-DD'. Empty string on failure."""
    if not raw:
        return ""
    try:
        return datetime.strptime(raw.strip(), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return raw.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_statement(
    pdf_path: Path,
) -> list[AccountSection]:
    """Parse a JPMorgan brokerage statement PDF.

    Returns a list of AccountSection objects (one for BROKERAGE, one for
    RETIREMENT BROKERAGE). Either may have an empty transactions list if
    nothing was parsed for that account.

    Statement Ending and Month Ending are always populated:
      - Statement Ending comes from the "Statement Period Ending" text on
        the page (or the most recent prior page that had one).
      - Month Ending is derived from the transaction's own date and is
        the last calendar day of that month.
    """
    logger.info("Opening PDF: %s", pdf_path)
    pages = _extract_pages(pdf_path)
    if not pages:
        logger.warning("No pages extracted from PDF")
        return [
            AccountSection(account_name=BROKERAGE_ACCOUNT),
            AccountSection(account_name=RETIREMENT_BROKERAGE_ACCOUNT),
        ]

    page_runs = _group_pages_by_account(pages)

    brokerage_txns: list[Transaction] = []
    retirement_txns: list[Transaction] = []

    for account, run_pages in page_runs:
        if account is None:
            continue
        flat_lines, page_for_line = _flatten_pages(run_pages)

        income_txns = _parse_income_blocks(flat_lines, page_for_line)
        trade_txns = _parse_trade_blocks(flat_lines, page_for_line)

        all_txns = income_txns + trade_txns
        all_txns.sort(key=lambda t: t.date)  # ISO dates sort lexically = chronologically

        if account == BROKERAGE_ACCOUNT:
            brokerage_txns.extend(all_txns)
        else:
            retirement_txns.extend(all_txns)

    logger.info("BROKERAGE total parsed: %d transactions", len(brokerage_txns))
    logger.info("RETIREMENT BROKERAGE total parsed: %d transactions", len(retirement_txns))

    return [
        AccountSection(account_name=BROKERAGE_ACCOUNT, transactions=brokerage_txns),
        AccountSection(account_name=RETIREMENT_BROKERAGE_ACCOUNT, transactions=retirement_txns),
    ]


# ---------------------------------------------------------------------------
# Page extraction & account detection
# ---------------------------------------------------------------------------


def _extract_pages(pdf_path: Path) -> list[_Page]:
    """Extract all PDF pages as filtered lines plus per-page metadata."""
    pages: list[_Page] = []
    statement_end_iso = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            raw_lines = text.splitlines()

            # Capture / refresh the statement-ending date (sticky across pages).
            page_se = ""
            for line in raw_lines:
                m = STATEMENT_END_PATTERN.search(line)
                if m:
                    page_se = normalize_statement_ending(m.group(1))
                    break
            if page_se:
                statement_end_iso = page_se

            cleaned = [
                ln.rstrip()
                for ln in raw_lines
                if ln.strip() and not any(p.search(ln) for p in NOISE_LINE_PATTERNS)
            ]

            page_obj = _Page(
                page_num=page_num,
                lines=cleaned,
                statement_ending=statement_end_iso,
                account=_detect_account_for_page(cleaned),
            )
            pages.append(page_obj)
            logger.debug(
                "Page %d: %d lines, account=%s, ending=%s",
                page_num,
                len(cleaned),
                page_obj.account,
                page_obj.statement_ending,
            )
    return pages


def _detect_account_for_page(lines: list[str]) -> str | None:
    """Look at the first ~10 lines to figure out which account this page is for."""
    head = lines[:10]
    for line in head:
        if BROKERAGE_ACCT_MARKER.search(line):
            return BROKERAGE_ACCOUNT
        if RETIREMENT_ACCT_MARKER.search(line):
            return RETIREMENT_BROKERAGE_ACCOUNT
    return None


def _group_pages_by_account(
    pages: list[_Page],
) -> list[tuple[str | None, list[_Page]]]:
    """Group consecutive pages with the same detected account into runs."""
    runs: list[tuple[str | None, list[_Page]]] = []
    current_account: str | None = None
    current_run: list[_Page] = []

    for page in pages:
        account = page.account or current_account
        if account != current_account:
            if current_run:
                runs.append((current_account, current_run))
            current_account = account
            current_run = []
        current_run.append(page)
    if current_run:
        runs.append((current_account, current_run))
    return runs


def _flatten_pages(pages: list[_Page]) -> tuple[list[str], list[_Page]]:
    """Flatten pages → (all_lines, parallel list mapping each line → its page)."""
    all_lines: list[str] = []
    page_for_line: list[_Page] = []
    for page in pages:
        for line in page.lines:
            all_lines.append(line)
            page_for_line.append(page)
    return all_lines, page_for_line


# ---------------------------------------------------------------------------
# INCOME parsing
# ---------------------------------------------------------------------------


def _parse_income_blocks(lines: list[str], page_for_line: list[_Page]) -> list[Transaction]:
    """Find every "Income from ... Investments" table and parse its rows."""
    transactions: list[Transaction] = []
    i = 0
    n = len(lines)
    while i < n:
        if INCOME_TABLE_HEADER.match(lines[i]):
            block_start = i + 1
            block_end = _find_block_end(lines, block_start, INCOME_END_MARKERS)
            txns = _parse_dated_block(
                lines[block_start:block_end],
                page_for_line[block_start:block_end],
                kind="income",
            )
            transactions.extend(txns)
            i = block_end
        else:
            i += 1
    return transactions


# ---------------------------------------------------------------------------
# TRADE parsing
# ---------------------------------------------------------------------------


def _parse_trade_blocks(lines: list[str], page_for_line: list[_Page]) -> list[Transaction]:
    """Find every "TRADE AND INVESTMENT ACTIVITY" table and parse its rows."""
    transactions: list[Transaction] = []
    i = 0
    n = len(lines)
    while i < n:
        if TRADE_SECTION_HEADER.match(lines[i]):
            block_start = i + 1
            block_end = _find_block_end(lines, block_start, TRADE_END_MARKERS)
            txns = _parse_dated_block(
                lines[block_start:block_end],
                page_for_line[block_start:block_end],
                kind="trade",
            )
            transactions.extend(txns)
            i = block_end
        else:
            i += 1
    return transactions


# ---------------------------------------------------------------------------
# Generic dated-block parser
# ---------------------------------------------------------------------------


def _find_block_end(lines: list[str], start: int, end_markers: list[re.Pattern]) -> int:
    """Find the index of the next end-marker after `start` (or len(lines))."""
    for j in range(start, len(lines)):
        if any(p.search(lines[j]) for p in end_markers):
            return j
    return len(lines)


def _is_new_transaction_start(line: str, kind: str, prev_lines: list[str]) -> bool:
    """Return True if this line should start a new transaction.

    A line starts a new transaction only if it begins with a date AND has
    a transaction-type keyword after the date.

    Special case for trade tables: even if a line begins with a date plus
    text, if the immediately preceding accumulated transaction is a trade
    (BUY/SELL/etc.) and that preceding row hasn't yet seen its settle date,
    treat this line as a settle-date continuation, NOT a new transaction.

    Examples in income blocks:
        "30 Mar 2026  BUY  VERIZON ..."  → True (date + type)
        "Symbol: VZ"                     → False (no date)

    Examples in trade blocks:
        "30 Mar 2026 BUY VERIZON ..."    → True
        "31 Mar 2026 UNSOLICITED ROME:"  → False when previous tx was BUY
                                           (it's the settle-date row + desc wrap)
    """
    date_match = DATE_PATTERN.match(line)
    if not date_match:
        return False
    remainder = line[date_match.end() :].strip()
    if not remainder:
        # Bare date — always a continuation
        return False
    has_type_token = bool(re.match(r"^[A-Z][A-Z &/\-]{1,}\b", remainder))
    if not has_type_token:
        return False

    # Trade-block special case: collapse settle date into the trade above.
    if kind == "trade" and prev_lines:
        first_prev = prev_lines[0]
        prev_date_match = DATE_PATTERN.match(first_prev)
        if prev_date_match:
            prev_remainder = first_prev[prev_date_match.end() :].strip()
            prev_first_token_match = re.match(r"^([A-Z][A-Z &/\-]*?)\b", prev_remainder)
            prev_first_token = (
                prev_first_token_match.group(1).strip() if prev_first_token_match else ""
            )
            if prev_first_token in _TRADE_TYPE_KEYWORDS:
                # Has the in-progress trade row already absorbed a settle date?
                # We allow exactly one date-prefixed continuation line per trade.
                continuation_dates = sum(1 for ln in prev_lines[1:] if DATE_PATTERN.match(ln))
                if continuation_dates == 0:
                    return False
    return True


def _parse_dated_block(
    block_lines: list[str],
    block_pages: list[_Page],
    *,
    kind: str,  # "income" or "trade"
) -> list[Transaction]:
    """Walk a slab of lines and emit one Transaction per date-prefixed group.

    A new transaction starts only on a line that has both a date AND a
    transaction-type keyword. Bare date lines (and trade-table settle-date
    lines) are treated as continuations of the row above.
    """
    transactions: list[Transaction] = []
    current_lines: list[str] = []
    current_pages: list[_Page] = []

    def flush() -> None:
        if not current_lines:
            return
        txn = _build_transaction(current_lines, current_pages, kind=kind)
        if txn is not None:
            transactions.append(txn)

    for line, page in zip(block_lines, block_pages, strict=False):
        if _is_new_transaction_start(line, kind, current_lines):
            flush()
            current_lines = [line]
            current_pages = [page]
        else:
            if current_lines:
                current_lines.append(line)
                current_pages.append(page)
    flush()
    return transactions


def _build_transaction(
    raw_lines: list[str],
    raw_pages: list[_Page],
    *,
    kind: str,
) -> Transaction | None:
    """Construct a Transaction from one or more contiguous PDF lines."""
    if not raw_lines:
        return None

    first = raw_lines[0]
    date_match = DATE_PATTERN.match(first)
    if not date_match:
        return None
    raw_date_str = date_match.group(1)
    rest_first = first[date_match.end() :].strip()

    # Combine all continuation lines for symbol & description discovery
    full_text = " ".join([rest_first, *raw_lines[1:]]).strip()

    # Determine the transaction TYPE (the first uppercase token after date)
    type_match = re.match(r"^\s*([A-Z][A-Z &/\-]*?)\b\s+", rest_first + " ")
    txn_type = (type_match.group(1).strip().upper() if type_match else "").strip()

    # Pull all money tokens from the FIRST line only — that's where the row's
    # numeric columns live. Continuation lines contain just description text.
    money_tokens_first = list(MONEY_PATTERN.finditer(first))
    primary_amount: float | None = None
    if money_tokens_first:
        primary_amount = parse_money(money_tokens_first[-1].group(0))

    # Statement Ending always populated from the page; Month Ending always
    # derived from the transaction's own date.
    statement_ending = (raw_pages[0].statement_ending if raw_pages else "") or ""
    month_ending = month_ending_for(raw_date_str)
    iso_date = to_iso_date(raw_date_str)

    txn = Transaction(
        date=iso_date,
        statement_ending=statement_ending,
        month_ending=month_ending,
    )
    _apply_type_rules(txn, txn_type, full_text, primary_amount, kind=kind)
    return txn


def _apply_type_rules(
    txn: Transaction,
    txn_type: str,
    full_text: str,
    amount: float | None,
    *,
    kind: str,
) -> None:
    """Apply the user-specified mapping rules for DIVIDEND / BUY / SELL / other."""
    type_normalized = txn_type.upper().strip()

    if type_normalized == "DIVIDEND":
        symbol = extract_symbol(full_text) or ""
        txn.account = "Dividends"
        txn.description = symbol
        txn.credit = amount
        return

    if type_normalized == "BUY":
        symbol = extract_symbol(full_text) or ""
        txn.account = "N/A"
        txn.description = f"{symbol} (buy)" if symbol else "(buy)"
        # Trade "Cost" appears in parens (outflow). Per spec, map to Debit
        # as a positive number ((10,062.00) → 10062.00 in Debit).
        txn.debit = abs(amount) if amount is not None else None
        return

    if type_normalized == "SELL":
        symbol = extract_symbol(full_text) or ""
        txn.account = "N/A"
        txn.description = f"{symbol} (sell)" if symbol else "(sell)"
        # Per spec: SELL maps Cost-style to Debit identically to BUY.
        txn.debit = abs(amount) if amount is not None else None
        return

    # Default mapping for income-section rows (INTEREST, ACH DEBIT, etc.)
    txn.account = txn_type.title() if txn_type else ""

    # Description = continuation text with money tokens & leading TYPE removed
    desc_text = _strip_money_tokens(full_text)
    if txn_type:
        desc_text = re.sub(
            r"^\s*" + re.escape(txn_type) + r"\s*", "", desc_text, flags=re.IGNORECASE
        )
    txn.description = desc_text.strip()

    # Default amount goes to Credit for income rows, Debit for trades
    if kind == "trade":
        txn.debit = abs(amount) if amount is not None else None
    else:
        txn.credit = amount


def _strip_money_tokens(text: str) -> str:
    """Remove all money-looking substrings from text."""
    return MONEY_PATTERN.sub("", text).strip()
