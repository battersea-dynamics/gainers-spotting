import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_stock_security_master.py"
SPEC = importlib.util.spec_from_file_location("build_stock_security_master", SCRIPT)
master = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(master)


HEADER = (
    "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|"
    "Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares\n"
)


class StockSecurityMasterTests(unittest.TestCase):
    def test_classifies_supported_stocks_and_explicit_non_stocks(self):
        content = (HEADER + "\n".join([
            "Y|A|Agilent Technologies, Inc. Common Stock|N| |N|100|N||A|A|N",
            "Y|BDRX|Biodexa plc - American Depositary Shares|Q|S|N|100|N|N||BDRX|N",
            "Y|ETF1|Example Momentum ETF|P| |Y|100|N||ETF1|ETF1|N",
            "Y|UNITU|Example Acquisition Corp - Units|Q|G|N|100|N|N||UNITU|N",
            "Y|WARW|Example Acquisition Corp - Warrant|Q|G|N|100|N|N||WARW|N",
            "Y|PREF$A|Example 7% Preferred Stock|N| |N|100|N||PREFpA|PREF-A|N",
            "Y|UNK|Example Holdings|N| |N|100|N||UNK|UNK|N",
        ])).encode()
        payload = master.build_payload(content, "fixture")
        by_symbol = {row["source_symbol"]: row for row in payload["securities"]}
        self.assertTrue(by_symbol["A"]["primary_stock_eligible"])
        self.assertEqual("adr_ads", by_symbol["BDRX"]["instrument_type"])
        self.assertEqual("pooled_product", by_symbol["ETF1"]["instrument_type"])
        self.assertEqual("unit", by_symbol["UNITU"]["instrument_type"])
        self.assertEqual("warrant", by_symbol["WARW"]["instrument_type"])
        self.assertEqual("preferred", by_symbol["PREF$A"]["instrument_type"])
        self.assertEqual("unknown", by_symbol["UNK"]["instrument_type"])
        self.assertFalse(by_symbol["UNK"]["primary_stock_eligible"])

    def test_generates_alpaca_aliases_for_nyse_suffixes(self):
        content = (HEADER + "\n".join([
            "Y|AAC.W|Example Warrant|N| |N|100|N||AAC.WS|AAC+|N",
            "Y|ABR$D|Example Preferred Stock|N| |N|100|N||ABRpD|ABR-D|N",
            "Y|AIIA.R|Example Rights|N| |N|100|N||AIIAr|AIIA^|N",
        ])).encode()
        rows = {row["source_symbol"]: row for row in master.parse_directory(content)}
        self.assertIn("AAC.WS", rows["AAC.W"]["aliases"])
        self.assertIn("ABR.PRD", rows["ABR$D"]["aliases"])
        self.assertIn("AIIA.RT", rows["AIIA.R"]["aliases"])

    def test_flags_spac_common_without_excluding_it(self):
        row = {
            "Security Name": "Example Acquisition Corporation Class A Ordinary Shares",
            "ETF": "N", "Test Issue": "N", "NextShares": "N",
        }
        result = master.classify_security(row)
        self.assertTrue(result["primary_stock_eligible"])
        self.assertTrue(result["possible_spac_common"])

    def test_issuer_name_words_do_not_override_explicit_stock_type(self):
        rows = {
            "RLX": "RLX Technology Inc. American Depositary Shares, each representing the right to receive one Class A ordinary share",
            "WDH": "Waterdrop Inc. American Depositary Shares (each representing the right to receive 10 Class A Ordinary Shares)",
            "PFBC": "Preferred Bank - Common Stock",
            "ASPS": "Altisource Portfolio Solutions S.A. - Common Stock",
            "OBAI": "Our Bond, Inc. - Common Stock",
        }
        for symbol, security_name in rows.items():
            with self.subTest(symbol=symbol):
                result = master.classify_security({
                    "Symbol": symbol,
                    "Security Name": security_name,
                    "ETF": "N",
                    "Test Issue": "N",
                    "NextShares": "N",
                })
                self.assertTrue(result["primary_stock_eligible"])
        self.assertEqual(
            "adr_ads",
            master.classify_security({
                "Symbol": "RLX",
                "Security Name": rows["RLX"],
                "ETF": "N",
                "Test Issue": "N",
                "NextShares": "N",
            })["instrument_type"],
        )

    def test_ambiguous_beneficial_interest_stays_out_without_reit_evidence(self):
        ambiguous = master.classify_security({
            "Symbol": "TRUST",
            "Security Name": "Example Income Trust Common Shares of Beneficial Interest",
            "ETF": "N",
            "Test Issue": "N",
            "NextShares": "N",
        })
        explicit_reit = master.classify_security({
            "Symbol": "REIT",
            "Security Name": "Example Trust (REIT) Common Shares of Beneficial Interest",
            "ETF": "N",
            "Test Issue": "N",
            "NextShares": "N",
        })
        self.assertEqual("unknown", ambiguous["instrument_type"])
        self.assertFalse(ambiguous["primary_stock_eligible"])
        self.assertEqual("common_shares", explicit_reit["instrument_type"])
        self.assertTrue(explicit_reit["primary_stock_eligible"])


if __name__ == "__main__":
    unittest.main()
