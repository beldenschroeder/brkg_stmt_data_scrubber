"""Unit tests for parser helpers, type-rule mapping, and dated-block parsing."""

from brkg_stmt_data_scrubber.parser import (
    _extract_symbol,
    _is_new_transaction_start,
    _month_ending_for,
    _normalize_statement_ending,
    _Page,
    _parse_dated_block,
    _parse_jpm_date,
    _parse_money,
    _to_iso_date,
)

# ---------------------------------------------------------------------------
# parse_money
# ---------------------------------------------------------------------------


class TestParseMoney:
    def test_plain_amount(self):
        assert _parse_money("123.45") == 123.45

    def test_dollar_sign(self):
        assert _parse_money("$123.45") == 123.45

    def test_with_comma(self):
        assert _parse_money("$1,234.56") == 1234.56

    def test_parentheses_negative(self):
        assert _parse_money("(123.45)") == -123.45

    def test_parentheses_negative_with_dollar_and_comma(self):
        assert _parse_money("($10,062.00)") == -10062.00

    def test_empty(self):
        assert _parse_money("") is None

    def test_whitespace_only(self):
        assert _parse_money("   ") is None

    def test_unparseable(self):
        assert _parse_money("abc") is None


# ---------------------------------------------------------------------------
# extract_symbol
# ---------------------------------------------------------------------------


class TestExtractSymbol:
    def test_basic(self):
        assert _extract_symbol("Apple Inc Symbol: AAPL") == "AAPL"

    def test_lowercase_keyword(self):
        assert _extract_symbol("apple inc symbol: aapl") == "AAPL"

    def test_with_dot(self):
        assert _extract_symbol("Berkshire Symbol: BRK.B") == "BRK.B"

    def test_no_symbol(self):
        assert _extract_symbol("Just a description") is None

    def test_empty(self):
        assert _extract_symbol("") is None


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


class TestDateHelpers:
    def test_parse_jpm_date_typical(self):
        dt = _parse_jpm_date("02 Mar 2026")
        assert dt is not None
        assert (dt.year, dt.month, dt.day) == (2026, 3, 2)

    def test_parse_jpm_date_invalid(self):
        assert _parse_jpm_date("not a date") is None

    def test_to_iso_date(self):
        assert _to_iso_date("02 Mar 2026") == "2026-03-02"
        assert _to_iso_date("31 Mar 2026") == "2026-03-31"

    def test_to_iso_date_passthrough_on_failure(self):
        assert _to_iso_date("garbage") == "garbage"

    def test_month_ending_for_march(self):
        assert _month_ending_for("02 Mar 2026") == "2026-03-31"

    def test_month_ending_for_february_leap_year(self):
        assert _month_ending_for("15 Feb 2024") == "2024-02-29"

    def test_month_ending_for_february_non_leap(self):
        assert _month_ending_for("15 Feb 2026") == "2026-02-28"

    def test_month_ending_for_invalid(self):
        assert _month_ending_for("nonsense") == ""

    def test_normalize_statement_ending(self):
        assert _normalize_statement_ending("March 31, 2026") == "2026-03-31"

    def test_normalize_statement_ending_passthrough_on_failure(self):
        assert _normalize_statement_ending("garbage") == "garbage"


# ---------------------------------------------------------------------------
# _is_new_transaction_start
# ---------------------------------------------------------------------------


class TestIsNewTransactionStart:
    def test_date_plus_type_is_new_tx(self):
        assert _is_new_transaction_start("02 Mar 2026 DIVIDEND APPLE INC", "income", []) is True

    def test_no_date_is_continuation(self):
        assert (
            _is_new_transaction_start("Symbol: AAPL", "income", ["02 Mar 2026 DIVIDEND ..."])
            is False
        )

    def test_date_only_is_continuation(self):
        assert (
            _is_new_transaction_start("31 Mar 2026", "trade", ["30 Mar 2026 BUY VZ ..."]) is False
        )

    def test_trade_settle_date_with_text_is_continuation(self):
        # Real-PDF case: "31 Mar 2026 UNSOLICITED ROME:" is a settle date row.
        prev = ["30 Mar 2026 BUY VERIZON COMMUNICATIONS 200 50.31 (10,062.00)"]
        assert _is_new_transaction_start("31 Mar 2026 UNSOLICITED ROME:", "trade", prev) is False

    def test_trade_after_settle_already_seen_is_new(self):
        # If the previous trade row already absorbed a settle date, the next
        # date+type line really is a new transaction.
        prev = [
            "30 Mar 2026 BUY VERIZON 200 50.31 (10,062.00)",
            "31 Mar 2026 UNSOLICITED ROME:",
            "Symbol: VZ",
        ]
        assert (
            _is_new_transaction_start("01 Apr 2026 SELL APPLE 10 200.00 2,000.00", "trade", prev)
            is True
        )

    def test_income_block_does_not_collapse_dates(self):
        # In income blocks, every date+type line is always a new transaction.
        prev = ["02 Mar 2026 DIVIDEND APPLE 10 1.00 10.00"]
        assert (
            _is_new_transaction_start("16 Mar 2026 DIVIDEND MSFT 5 0.5 2.50", "income", prev)
            is True
        )


# ---------------------------------------------------------------------------
# _parse_dated_block — end-to-end on synthetic line input
# ---------------------------------------------------------------------------


def _pages_for(lines):
    """Build a parallel _Page list (one shared page) for synthetic line inputs."""
    page = _Page(page_num=1, lines=list(lines), statement_ending="2026-03-31", account="BROKERAGE")
    return [page] * len(lines)


class TestParseDatedBlockIncome:
    def test_dividend_simple_one_line(self):
        lines = ["02 Mar 2026 DIVIDEND APPLE INC Symbol: AAPL 100.00 100.00"]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="income")
        assert len(txns) == 1
        assert txns[0].date == "2026-03-02"  # ISO format
        assert txns[0].account == "Dividends"
        assert txns[0].description == "AAPL"
        assert txns[0].credit == 100.00
        assert txns[0].debit is None
        assert txns[0].statement_ending == "2026-03-31"
        assert txns[0].month_ending == ""

    def test_dividend_with_continuation_lines(self):
        # Mirrors the real PDF: amount on first line, symbol on a later continuation line.
        lines = [
            "02 Mar 2026 DIVIDEND JPMORGAN 100% U S 12.20 12.20",
            "TREASURY SECURITIES MM FUND",
            "MORGAN SH C RECORD 02/27/26",
            "PAY 02/27/26",
            "Symbol: HTSXX",
        ]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="income")
        assert len(txns) == 1
        assert txns[0].date == "2026-03-02"
        assert txns[0].account == "Dividends"
        assert txns[0].description == "HTSXX"
        assert txns[0].credit == 12.20

    def test_multiple_dividends_each_with_continuations(self):
        lines = [
            "12 Mar 2026 DIVIDEND MICROSOFT CORP 19 0.91 17.29 17.29",
            "CASH DIV ON 19 SHS REC",
            "Symbol: MSFT",
            "16 Mar 2026 DIVIDEND ALPHABET INC 26 0.21 5.46 5.46",
            "Symbol: GOOGL",
        ]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="income")
        assert len(txns) == 2
        assert (txns[0].date, txns[0].description, txns[0].credit) == ("2026-03-12", "MSFT", 17.29)
        assert (txns[1].date, txns[1].description, txns[1].credit) == ("2026-03-16", "GOOGL", 5.46)

    def test_negative_amount_in_parens(self):
        lines = ["19 Mar 2026 ADJUSTMENT REVERSAL OF DIVIDEND (25.00)"]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="income")
        assert len(txns) == 1
        assert txns[0].credit == -25.00


class TestParseDatedBlockTrade:
    def test_buy_with_settle_date_and_symbol_continuation(self):
        # Reproduces the bug-fix scenario from the real PDF.
        lines = [
            "30 Mar 2026 BUY VERIZON COMMUNICATIONS 200 50.31 (10,062.00)",
            "31 Mar 2026 UNSOLICITED ROME:",
            "WHIPANYAAG26033007776",
            "Symbol: VZ",
        ]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="trade")
        assert len(txns) == 1, "settle-date line must NOT spawn a phantom row"
        assert txns[0].date == "2026-03-30"  # ISO format
        assert txns[0].account == "N/A"
        assert txns[0].description == "VZ (buy)"
        assert txns[0].debit == 10062.00
        assert txns[0].credit is None

    def test_sell_maps_to_debit(self):
        lines = ["10 Mar 2026 SELL APPLE INC 5 200.00 1,000.00", "Symbol: AAPL"]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="trade")
        assert len(txns) == 1
        assert txns[0].date == "2026-03-10"
        assert txns[0].account == "N/A"
        assert txns[0].description == "AAPL (sell)"
        assert txns[0].debit == 1000.00

    def test_two_buys_in_a_row(self):
        lines = [
            "10 Mar 2026 BUY APPLE 5 200.00 (1,000.00)",
            "11 Mar 2026 UNSOLICITED",
            "Symbol: AAPL",
            "20 Mar 2026 BUY MICROSOFT 3 300.00 (900.00)",
            "21 Mar 2026 UNSOLICITED",
            "Symbol: MSFT",
        ]
        txns = _parse_dated_block(lines, _pages_for(lines), kind="trade")
        assert len(txns) == 2
        assert (txns[0].date, txns[0].description, txns[0].debit) == (
            "2026-03-10",
            "AAPL (buy)",
            1000.00,
        )
        assert (txns[1].date, txns[1].description, txns[1].debit) == (
            "2026-03-20",
            "MSFT (buy)",
            900.00,
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_block(self):
        assert _parse_dated_block([], [], kind="income") == []

    def test_block_with_no_date_lines(self):
        lines = ["Some header text", "Another non-date line"]
        result = _parse_dated_block(lines, _pages_for(lines), kind="income")
        assert result == []
