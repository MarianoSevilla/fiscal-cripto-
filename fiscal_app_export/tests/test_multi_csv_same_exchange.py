"""Conservative multi-CSV coverage with actual fiscal CSV signatures and an oracle."""
import csv
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from multi_csv_same_exchange import ID_COLUMNS, MultiCsvUserError, merge_csv_same_exchange
from clasificador_bitvavo import ClasificadorBitvavo
from motor_fifo import MotorFIFO
from app import procesar_bitvavo, FiscalImportError

BITVAVO = ['Timezone','Date','Time','Type','Currency','Amount','Quote Currency','Quote Price',
           'Received / Paid Currency','Received / Paid Amount','Fee currency','Fee amount',
           'Status','Transaction ID','Address']
KRAKEN = ['txid','refid','time','type','subtype','aclass','subclass','asset','wallet','amount','fee','balance']
COINBASE = ['ID','Timestamp','Transaction Type','Asset','Quantity Transacted','Price Currency',
            'Price at Transaction','Subtotal','Total (inclusive of fees and/or spread)',
            'Fees and/or Spread','Notes','Sender Address','Recipient Address']
UPHOLD = ['Date','Destination','Destination Amount','Destination Currency','Fee Amount',
          'Fee Currency','Id','Origin','Origin Amount','Origin Currency','Status','Type']

B_ROWS = [
    ['UTC','2023-01-01','10:00:00.100','buy','BTC','2','EUR','100','EUR','-200','EUR','0','Completed','b1',''],
    ['UTC','2023-01-01','10:00:00.900','buy','BTC','1','EUR','300','EUR','-300','EUR','0','Completed','b2',''],
    ['UTC','2025-01-01','10:00:00','sell','BTC','-1','EUR','500','EUR','500','EUR','0','Completed','s1',''],
]
K_ROWS = [
    ['b1a','b1','2023-01-01 10:00:00','spend','','currency','','EUR','spot','-200','0','0'],
    ['b1b','b1','2023-01-01 10:00:00','receive','','currency','','BTC','spot','2','0','0'],
    ['b2a','b2','2024-01-01 10:00:00','spend','','currency','','EUR','spot','-300','0','0'],
    ['b2b','b2','2024-01-01 10:00:00','receive','','currency','','BTC','spot','1','0','0'],
]
C_ROWS = [
    ['b1','2023-01-01T10:00:00Z','Buy','BTC','2','EUR','100','200','200','0','','',''],
    ['b2','2024-01-01T10:00:00Z','Buy','BTC','1','EUR','300','300','300','0','','',''],
]
U_ROWS = [
    ['Sun Jan 01 2023 10:00:00 GMT+0000','uphold','2','BTC','','','b1','credit-card','200','EUR','completed','in'],
    ['Mon Jan 01 2024 10:00:00 GMT+0000','uphold','1','BTC','','','b2','credit-card','300','EUR','completed','in'],
]


class MultiCsvTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = pathlib.Path(temp.name)

    def create(self, name, header, rows, delimiter=',', encoding='utf-8', preamble=''):
        file = self.dir / name
        with file.open('w', encoding=encoding, newline='') as stream:
            stream.write(preamble)
            writer = csv.writer(stream, delimiter=delimiter)
            writer.writerow(header)
            writer.writerows(rows)
        return str(file)

    def merge(self, exchange, files):
        result = str(self.dir / 'combined.csv')
        stats = merge_csv_same_exchange(files, exchange, result)
        with open(result, newline='', encoding='utf-8') as stream:
            rows = list(csv.reader(stream))
        return stats, rows

    def test_native_id_contracts_actual_headers(self):
        for ex, header, records in [
            ('bitvavo', BITVAVO, B_ROWS), ('coinbase', COINBASE, C_ROWS),
            ('kraken', KRAKEN, K_ROWS), ('uphold', UPHOLD, U_ROWS)
        ]:
            with self.subTest(exchange=ex):
                one = self.create(ex+'1.csv', header, records[:1])
                two = self.create(ex+'2.csv', header, records)
                summary, rows = self.merge(ex, [one, two])
                self.assertEqual(summary['duplicates_removed'], 1)
                self.assertEqual(summary['rows'], len(records))
                self.assertEqual(len(rows), len(records)+1)

    def test_disjoint_periods(self):
        one = self.create('first.csv', KRAKEN, K_ROWS[:2])
        two = self.create('second.csv', KRAKEN, K_ROWS[2:])
        summary, _ = self.merge('kraken', [two, one])
        self.assertEqual(summary['rows'], 4)

    def test_conflicting_id_rejected(self):
        original = self.create('first.csv', KRAKEN, K_ROWS[:1])
        changed = [x[:] for x in K_ROWS[:1]]
        changed[0][9] = '-999'
        second = self.create('second.csv', KRAKEN, changed)
        with self.assertRaisesRegex(MultiCsvUserError, 'datos diferentes'):
            self.merge('kraken', [original, second])
        self.assertFalse((self.dir/'combined.csv').exists())

    def test_missing_id_rejected(self):
        first = self.create('first.csv', KRAKEN, K_ROWS[:1])
        bad = [x[:] for x in K_ROWS[:1]]
        bad[0][0] = ''
        second = self.create('second.csv', KRAKEN, bad)
        with self.assertRaisesRegex(MultiCsvUserError, 'sin identificador'):
            self.merge('kraken', [first, second])

    def test_reordered_header(self):
        first = self.create('first.csv', KRAKEN, K_ROWS[:2])
        reverse = list(reversed(range(len(KRAKEN))))
        second = self.create('second.csv', [KRAKEN[i] for i in reverse],
                             [[r[i] for i in reverse] for r in K_ROWS[2:]])
        stats, rows = self.merge('kraken', [first, second])
        self.assertEqual(rows[1:], K_ROWS)

    def test_mismatched_header(self):
        first = self.create('first.csv', KRAKEN, K_ROWS[:1])
        second = self.create('second.csv', KRAKEN[:-1], [r[:-1] for r in K_ROWS[1:2]])
        with self.assertRaisesRegex(MultiCsvUserError, 'cabecera distintas'):
            self.merge('kraken', [first, second])

    def test_unsupported_exchange(self):
        with self.assertRaises(MultiCsvUserError):
            merge_csv_same_exchange(['a','b'], 'binance', str(self.dir/'out'))

    def test_single_file(self):
        with self.assertRaises(MultiCsvUserError):
            merge_csv_same_exchange(['a'], 'kraken', str(self.dir/'out'))

    def test_malformed_row(self):
        one = self.create('first.csv', KRAKEN, K_ROWS[:1])
        two = self.create('second.csv', KRAKEN, [K_ROWS[1]+['extra']])
        with self.assertRaisesRegex(MultiCsvUserError, 'no coincide'):
            self.merge('kraken', [one, two])

    def _gain_bitvavo(self, source):
        c = ClasificadorBitvavo(source).clasificar()
        m = MotorFIFO()
        for op in sorted(c.compraventas, key=lambda x:x.fecha):
            if op.tipo == 'COMPRA':
                m.registrar_compra(fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                                  importe=op.importe, contraparte=op.contraparte,
                                  fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad)
            else:
                m.registrar_venta(fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                                  importe=op.importe, contraparte=op.contraparte,
                                  fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad)
        return m.resultados[0].ganancia_perdida, m.resultados[0].precio_coste

    def test_fiscal_oracle_millisecond_file_order(self):
        full = self.create('full.csv', BITVAVO, B_ROWS)
        later = self.create('later.csv', BITVAVO, [B_ROWS[1]])
        earlier = self.create('earlier.csv', BITVAVO, [B_ROWS[0], B_ROWS[2]])
        self.merge('bitvavo', [later, earlier])
        self.assertEqual(self._gain_bitvavo(full), (400.0, 100.0))
        self.assertEqual(self._gain_bitvavo(str(self.dir/'combined.csv')), (400.0, 100.0))

    def test_genuine_tie_blocks_instead_of_guessing(self):
        original = [x[:] for x in B_ROWS]
        original[1][2] = original[0][2]
        later = self.create('later.csv', BITVAVO, [original[1]])
        earlier = self.create('earlier.csv', BITVAVO, [original[0], original[2]])
        full = self.create('full.csv', BITVAVO, original)
        self.merge('bitvavo', [later, earlier])
        with self.assertRaisesRegex(FiscalImportError, 'orden'):
            procesar_bitvavo(full)
        with self.assertRaisesRegex(FiscalImportError, 'orden'):
            procesar_bitvavo(str(self.dir / 'combined.csv'))

    def test_bitvavo_non_comma_and_latin1(self):
        special = [x[:] for x in B_ROWS]
        special[0][-1] = 'synthetic-é'
        for index, (sep, encoding) in enumerate([(';', 'utf-8'), ('\t','utf-8'), (',','latin1')]):
            with self.subTest(sep=sep,encoding=encoding):
                f1 = self.create(f'one{index}.csv', BITVAVO, special[:1], delimiter=sep, encoding=encoding)
                f2 = self.create(f'two{index}.csv', BITVAVO, special[1:], delimiter=sep, encoding=encoding)
                stats, data = self.merge('bitvavo', [f1, f2])
                self.assertEqual(stats['rows'], 3)
                self.assertEqual(data[1][-1], 'synthetic-é')

    def test_bounds_before_large_record_materialization(self):
        huge_header = ['txid', 'time'] + [f'extra_{i}' for i in range(100)]
        a = self.create('wide1.csv', huge_header, [['a','2023-01-01']+['0']*100])
        b = self.create('wide2.csv', huge_header, [['b','2023-01-02']+['0']*100])
        with self.assertRaisesRegex(MultiCsvUserError, 'extensas'):
            self.merge('kraken', [a,b])

    def test_no_missing_year_when_rows_reordered(self):
        original = self.create('first.csv', COINBASE, C_ROWS[:1])
        later = self.create('second.csv', COINBASE, C_ROWS[1:])
        stats, rows = self.merge('coinbase', [later, original])
        self.assertEqual(stats['rows'], 2)
        self.assertEqual([r[1] for r in rows[1:]], [x[1] for x in C_ROWS])


if __name__ == '__main__':
    unittest.main()
