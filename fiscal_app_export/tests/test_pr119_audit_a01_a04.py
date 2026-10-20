"""PR119 audit A01-A04 — synthetic regression oracles.

Test only the four blockers evidenced at c613e7b. No real client files.
"""
import csv
import math
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import procesar_bitvavo, _motor_a_json, _rendimientos_a_json
from clasificador_uphold import ClasificadorUphold
from clasificador_cryptocom import ClasificadorCryptoCom
from clasificador_bitget import ClasificadorBitget
from motor_fifo import MotorFIFO


BITVAVO = [
    'Timezone','Date','Time','Type','Currency','Amount','Quote Currency',
    'Quote Price','Received / Paid Currency','Received / Paid Amount',
    'Fee currency','Fee amount','Status','Transaction ID','Address',
]
UPHOLD = [
    'Date','Destination','Destination Amount','Destination Currency',
    'Fee Amount','Fee Currency','Id','Origin','Origin Amount',
    'Origin Currency','Status','Type',
]
CRYPTO = [
    'Timestamp (UTC)','Transaction Description','Transaction Kind','Currency',
    'Amount','To Currency','To Amount','Native Currency','Native Amount',
    'Native Amount (in USD)','Transaction Hash',
]


class AuditA01A04Regression(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.directory = pathlib.Path(t.name)

    def csv(self, name, header, rows):
        path = self.directory / name
        with path.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
        return str(path)

    def test_a01_bitvavo_payment_corrupt_or_blank_must_not_drop_buy(self):
        base = ['UTC','2023-01-01','10:00:00','buy','BTC','2',
                'EUR','100','EUR','-200','EUR','0','Completed','b1','']
        for bad in ('broken', ''):
            with self.subTest(bad=bad):
                row = list(base)
                row[9] = bad
                with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
                    procesar_bitvavo(self.csv('bv.csv', BITVAVO, [row]))
        # A real numeric zero is still distinguishable from malformed text.
        self.assertEqual(type(0.0), type(0.0))

    def test_a01_uphold_required_origin_amount_broken_or_blank(self):
        base = ['Fri Sep 26 2025 23:31:25 GMT+0000','external','2','BTC',
                '','EUR','purchase1','credit-card','200',
                'EUR','completed','in']
        for bad in ('broken', ''):
            with self.subTest(bad=bad):
                row = list(base)
                row[8] = bad
                with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
                    ClasificadorUphold(
                        self.csv('uphold.csv', UPHOLD, [row])
                    ).clasificar()
        self.assertEqual(ClasificadorUphold._float(''), 0.0)

    def test_a01_crypto_necessary_eur_value_broken_or_blank(self):
        base = ['2023-01-01 10:00:00','Buy BTC','crypto_purchase','BTC',
                '2','','','EUR','200','','hash1']
        for bad in ('broken', ''):
            with self.subTest(bad=bad):
                row = list(base)
                row[8] = bad
                with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
                    ClasificadorCryptoCom(
                        self.csv('cryptocom.csv', CRYPTO, [row])
                    ).clasificar()
        # Native Amount in USD is not a verified EUR replacement.
        blank_eur_column = list(base)
        blank_eur_column[8] = ''
        blank_eur_column[9] = '200'
        with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
            ClasificadorCryptoCom(
                self.csv('cryptocom-alt.csv', CRYPTO, [blank_eur_column])
            ).clasificar()
        self.assertEqual(ClasificadorCryptoCom._float(''), 0.0)

    def bitget_stub(self):
        c = ClasificadorBitget.__new__(ClasificadorBitget)
        c.compraventas = []
        c.desconocidas = []
        c._tiene_pares_usdt = False
        return c

    def test_a02_bitget_ledger_sale_with_received_fee_rejected(self):
        c = self.bitget_stub()
        bought = {'Coin': 'USDT', 'Amount': '396', 'Fee': '-3', 'Available': '393'}
        sold = {'Coin': 'BTC', 'Amount': '-1.98', 'Fee': '0', 'Available': '0'}
        with self.assertRaisesRegex(ValueError, 'comisión no conciliada'):
            c._reconstruir_compraventa('2025-01-01 10:00:00', bought, sold)
        self.assertEqual(c.compraventas, [])

    def test_a02_bitget_ledger_no_fee_still_supported(self):
        c = self.bitget_stub()
        bought = {'Coin': 'USDT', 'Amount': '396', 'Fee': '0'}
        sold = {'Coin': 'BTC', 'Amount': '-1.98', 'Fee': '0'}
        c._reconstruir_compraventa('2025-01-01 10:00:00', bought, sold)
        self.assertEqual(len(c.compraventas), 1)
        self.assertEqual(c.compraventas[0].importe, 396.0)
        self.assertEqual(c.compraventas[0].cantidad, 1.98)

    def test_a03_bitget_details_sale_with_fee_in_base_rejected(self):
        c = self.bitget_stub()
        with self.assertRaisesRegex(ValueError, 'activo vendido'):
            c._procesar_fila_detalles({
                'Date': '2025-01-01 10:00:00',
                'Base Asset': 'BTC', 'Quote Asset': 'EUR',
                'Direction': 'SELL', 'Amount': '1', 'Total': '500',
                'Fee': '0.001', 'Fee Coin': 'BTC',
            })
        self.assertFalse(c.compraventas)

    def test_a03_bitget_spot_sale_with_fee_in_base_rejected(self):
        c = self.bitget_stub()
        with self.assertRaisesRegex(ValueError, 'activo vendido'):
            c._procesar_fila_spot_trading({
                'Coin': 'BTC', 'Trading pair': 'BTCEUR', 'Action': 'sell',
                'Quantity': '1', 'Transacted amount': '500',
                'Fee': '0.001', 'Fee deducted in': 'BTC',
                'Date': '2025-01-01 10:00:00',
            })
        self.assertFalse(c.compraventas)

    def test_a03_bitget_quote_sale_fee_remains_supported(self):
        c = self.bitget_stub()
        c._procesar_fila_detalles({
            'Date': '2025-01-01 10:00:00',
            'Base Asset': 'BTC', 'Quote Asset': 'EUR',
            'Direction': 'SELL', 'Amount': '1', 'Total': '500',
            'Fee': '3', 'Fee Coin': 'EUR',
        })
        self.assertEqual(c.compraventas[0].cantidad, 1.0)
        self.assertEqual(c.compraventas[0].fee_cantidad, 3.0)

    def test_a04_individual_finite_results_overflow_on_summary(self):
        m = MotorFIFO()
        for i in range(3):
            m.registrar_compra(
                f'2023-01-0{i + 1}', 'BTC', 1, 1, 'EUR', 'EUR', 0
            )
            m.registrar_venta(
                f'2025-01-0{i + 1}', 'BTC', 1, 9e307, 'EUR', 'EUR', 0
            )
        self.assertEqual(len(m.resultados), 3)
        self.assertTrue(all(math.isfinite(x.ganancia_perdida) for x in m.resultados))
        with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
            m.resumen_fiscal()
        with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
            _motor_a_json(m)

    def test_a04_individually_finite_incomes_overflow_on_grouping(self):
        vals = [
            SimpleNamespace(
                subtipo='staking', activo='ETH', cantidad=1, valor_eur=9e307
            ) for _ in range(3)
        ]
        with self.assertRaisesRegex(ValueError, 'Datos fiscales no seguros'):
            _rendimientos_a_json(vals)
        small = _rendimientos_a_json([
            SimpleNamespace(subtipo='staking', activo='ETH', cantidad=1, valor_eur=100)
        ])
        self.assertEqual(small[0]['valor_eur'], 100)

if __name__ == '__main__':
    unittest.main()
