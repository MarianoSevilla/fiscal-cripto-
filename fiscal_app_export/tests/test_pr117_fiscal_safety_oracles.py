"""Independent fiscal oracles derived from PR #117 adversarial audit (synthetic only)."""
import csv
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import FiscalImportError, procesar_coinbase, procesar_kraken

KRAKEN = ['txid','refid','time','type','subtype','aclass','subclass','asset','wallet','amount','fee','balance']
COINBASE = ['ID','Timestamp','Transaction Type','Asset','Quantity Transacted',
            'Price Currency','Price at Transaction','Subtotal',
            'Total (inclusive of fees and/or spread)','Fees and/or Spread',
            'Notes','Sender Address','Recipient Address']


class FiscalSafetyOracles(unittest.TestCase):
    def save(self, columns, rows):
        temporary = tempfile.NamedTemporaryFile(suffix='.csv', delete=False)
        path = pathlib.Path(temporary.name)
        temporary.close()
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)
        return str(path)

    def test_kraken_unsupported_trade_fails_closed(self):
        # Official ledger type trade must not produce success with zero operations.
        rows = [
            ['b1a','b1','2023-01-01 10:00:00','trade','','currency','','EUR','spot','-200','0','0'],
            ['b1b','b1','2023-01-01 10:00:00','trade','','currency','','BTC','spot','2','0','0'],
            ['s1a','s1','2025-01-01 10:00:00','trade','','currency','','BTC','spot','-1','0','0'],
            ['s1b','s1','2025-01-01 10:00:00','trade','','currency','','EUR','spot','500','0','0'],
        ]
        with self.assertRaisesRegex(FiscalImportError, 'trade'):
            procesar_kraken(self.save(KRAKEN, rows))

    def test_coinbase_convert_uses_explicit_eur_market_value(self):
        rows = [
            ['b1','2023-01-01T10:00:00Z','Buy','2','BTC','EUR','100',
             '200','200','0','','',''],
            ['c1','2025-01-01T10:00:00Z','Convert','1','BTC','EUR','500',
             '500','500','0','Converted 1 BTC to 10 ETH','',''],
        ]
        motor, _, _ = procesar_coinbase(self.save(COINBASE, rows))
        self.assertEqual(len(motor.resultados), 1)
        sale = motor.resultados[0]
        self.assertAlmostEqual(sale.precio_coste, 100)
        self.assertAlmostEqual(sale.precio_transmision, 500)
        self.assertAlmostEqual(sale.ganancia_perdida, 400)
        self.assertAlmostEqual(motor.inventario["ETH"][0].precio_coste_unitario, 50)

    def test_coinbase_without_eur_valuation_fails_closed(self):
        rows = [
            ['b1','2023-01-01T10:00:00Z','Buy','2','BTC','EUR','100',
             '200','200','0','','',''],
            ['c1','2025-01-01T10:00:00Z','Convert','1','BTC','EUR','0',
             '0','0','0','Converted 1 BTC to 10 ETH','',''],
        ]
        with self.assertRaisesRegex(FiscalImportError, 'valoración EUR'):
            procesar_coinbase(self.save(COINBASE, rows))


if __name__ == '__main__':
    unittest.main()
