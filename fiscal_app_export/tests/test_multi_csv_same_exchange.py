"""Synthetic tests for the conservative same-exchange CSV consolidation."""
import csv
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from multi_csv_same_exchange import ID_COLUMNS, MultiCsvUserError, merge_csv_same_exchange


class MultiCsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name)

    def csv(self, name, header, rows, preamble=None):
        p = self.path / name
        with p.open("w", encoding="utf-8", newline="") as f:
            if preamble:
                f.write(preamble)
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        return str(p)

    def merge(self, exchange, inputs):
        target = str(self.path / "combined.csv")
        stats = merge_csv_same_exchange(inputs, exchange, target)
        with open(target, newline="", encoding="utf-8") as f:
            return stats, list(csv.reader(f))

    def test_four_exchange_contracts(self):
        for exchange, id_col in ID_COLUMNS.items():
            with self.subTest(exchange=exchange):
                header = [id_col, "Timestamp", "Transaction Type", "Asset", "Quantity Transacted"] if exchange == "coinbase" else [id_col, "date", "amount"]
                pre = "Account statement\nGenerated for synthetic testing\n" if exchange == "coinbase" else ""
                arow = ["a", "2026-01-01", "Buy", "BTC", "1"] if exchange == "coinbase" else ["a", "2026-01-01", "1"]
                brow = ["b", "2026-02-01", "Sell", "BTC", "1"] if exchange == "coinbase" else ["b", "2026-02-01", "2"]
                a = self.csv(exchange+"1.csv", header, [arow], pre)
                b = self.csv(exchange+"2.csv", header, [arow, brow], pre)
                stats, rows = self.merge(exchange, [a, b])
                self.assertEqual(stats, {"files": 2, "rows": 2, "duplicates_removed": 1})
                self.assertEqual(len(rows), 3)

    def test_disjoint_periods_supported(self):
        a=self.csv("a.csv",["txid","time"],[["old","2022-01-01"]])
        b=self.csv("b.csv",["txid","time"],[["new","2026-01-01"]])
        stats,_=self.merge("kraken",[a,b])
        self.assertEqual(stats["rows"],2)

    def test_conflicting_id_rejected_without_partial_output(self):
        a=self.csv("a.csv",["txid","amount"],[["a","1"]])
        b=self.csv("b.csv",["txid","amount"],[["a","2"]])
        with self.assertRaisesRegex(MultiCsvUserError,"datos diferentes"):
            self.merge("kraken",[a,b])
        self.assertFalse((self.path/"combined.csv").exists())

    def test_missing_id_rejected(self):
        a=self.csv("a.csv",["txid","amount"],[["a","1"]])
        b=self.csv("b.csv",["txid","amount"],[["","2"]])
        with self.assertRaisesRegex(MultiCsvUserError,"sin identificador"):
            self.merge("kraken",[a,b])

    def test_mismatched_header_rejected(self):
        a=self.csv("a.csv",["txid","amount"],[["a","1"]])
        b=self.csv("b.csv",["txid","value"],[["b","2"]])
        with self.assertRaisesRegex(MultiCsvUserError,"cabecera distintas"):
            self.merge("kraken",[a,b])

    def test_reordered_headers_preserve_values(self):
        a=self.csv("a.csv",["txid","amount"],[["a","1"]])
        b=self.csv("b.csv",["amount","txid"],[["2","b"]])
        _, rows = self.merge("kraken",[a,b])
        self.assertEqual(rows,[["txid","amount"],["a","1"],["b","2"]])

    def test_exchange_without_safe_policy_rejected(self):
        with self.assertRaises(MultiCsvUserError):
            merge_csv_same_exchange(["a","b"],"binance",str(self.path/"combined.csv"))

    def test_single_file_rejected_from_multi_path(self):
        with self.assertRaises(MultiCsvUserError):
            merge_csv_same_exchange(["a"],"kraken",str(self.path/"combined.csv"))

    def test_malformed_row_rejected(self):
        a=self.csv("a.csv",["txid","amount"],[["a","1"]])
        b=self.csv("b.csv",["txid","amount"],[["b","2","extra"]])
        with self.assertRaisesRegex(MultiCsvUserError,"no coincide"):
            self.merge("kraken",[a,b])


if __name__ == "__main__":
    unittest.main()
