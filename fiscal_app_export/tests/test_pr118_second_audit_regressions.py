"""PR #118 second Work audit: fiscal boundary regression oracles (synthetic).

Execute against source, not a mock FIFO. Cover the single-file path and
the native-ID merge to stop order, currency and tax-year regressions.
"""
import csv
import inspect
import io
import math
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import (app, FiscalImportError, procesar_bitvavo, procesar_coinbase,
                 procesar_uphold, procesar_nexo)
from multi_csv_same_exchange import merge_csv_same_exchange
from clasificador_uphold import ClasificadorUphold

B = ['Timezone','Date','Time','Type','Currency','Amount','Quote Currency','Quote Price',
     'Received / Paid Currency','Received / Paid Amount','Fee currency','Fee amount',
     'Status','Transaction ID','Address']
C = ['ID','Timestamp','Transaction Type','Asset','Quantity Transacted','Price Currency',
     'Price at Transaction','Subtotal','Total (inclusive of fees and/or spread)',
     'Fees and/or Spread','Notes','Sender Address','Recipient Address']
U = ['Date','Destination','Destination Amount','Destination Currency','Fee Amount',
     'Fee Currency','Id','Origin','Origin Amount','Origin Currency','Status','Type']


def buy_b(id, date, time, qty, price):
    amount = float(qty) * float(price)
    return ['UTC',date,time,'buy','BTC',str(qty),'EUR',str(price),'EUR',
            str(-amount),'EUR','0','Completed',id,'']


def buy_c(id, date, asset, qty, total, currency='EUR'):
    return [id,date,'Buy',asset,str(qty),currency,str(total),
            str(total),str(total),'0','','','']


def convert_c(id, date, asset, qty, received, received_qty, fmv, currency='EUR'):
    return [id,date,'Convert',asset,str(qty),currency,str(fmv),
            str(fmv),str(fmv),'0',
            f'Converted {qty} {asset} to {received_qty} {received}','','']


class SecondAuditFiscalOracles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = pathlib.Path(self.temp.name)

    def csv(self, name, header, rows):
        path = self.dir / name
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(header); w.writerows(rows)
        return str(path)

    def combined(self, exchange, header, rows_a, rows_b):
        left = self.csv(exchange+'a.csv',header,rows_a)
        right = self.csv(exchange+'b.csv',header,rows_b)
        out = str(self.dir / (exchange+'merged.csv'))
        merge_csv_same_exchange([left,right],exchange,out)
        return out

    def test_r01_dependent_swaps_equal_time_rejected_in_single_and_both_merge_orders(self):
        stamp = '2025-01-01T10:00:00Z'
        base = buy_c('b1','2023-01-01T10:00:00Z','ETH',1,100)
        first = convert_c('x1',stamp,'ETH',1,'BTC',1,500)
        second = convert_c('x2',stamp,'BTC',1,'SOL',1,600)
        full = self.csv('all.csv', C, [base,first,second])
        with self.assertRaisesRegex(FiscalImportError,'orden'):
            procesar_coinbase(full)
        for first_rows,second_rows in [([base,first],[second]),([second],[base,first])]:
            merged = self.combined('coinbase',C,first_rows,second_rows)
            with self.assertRaisesRegex(FiscalImportError,'orden'):
                procesar_coinbase(merged)

    def test_r05_equal_time_identical_economic_buys_retained(self):
        row1=buy_b('b1','2023-01-01','10:00:00',2,100)
        row2=buy_b('b2','2023-01-01','10:00:00',2,100)
        sale=['UTC','2025-01-01','10:00:00','sell','BTC','-1','EUR','500',
              'EUR','500','EUR','0','Completed','s1','']
        full=self.csv('full.csv',B,[row1,row2,sale])
        merged=self.combined('bitvavo',B,[row1,sale],[row2])
        for path in (full,merged):
            motor,_,_=procesar_bitvavo(path)
            self.assertAlmostEqual(motor.resultados[0].ganancia_perdida,400)
            self.assertAlmostEqual(
                sum(l.cantidad_restante for l in motor.inventario['BTC']),3)

    def test_r01_unequal_cost_ties_rejected_single_and_multi(self):
        row1=buy_b('b1','2023-01-01','10:00:00',2,100)
        row2=buy_b('b2','2023-01-01','10:00:00',1,300)
        sale=['UTC','2025-01-01','10:00:00','sell','BTC','-1','EUR','500',
              'EUR','500','EUR','0','Completed','s1','']
        full=self.csv('full.csv',B,[row1,row2,sale])
        merged=self.combined('bitvavo',B,[row2],[row1,sale])
        for path in (full,merged):
            with self.assertRaisesRegex(FiscalImportError,'orden'):
                procesar_bitvavo(path)

    def test_r02_eur_coinbase_and_non_eur_rejection(self):
        orig=buy_c('b1','2023-01-01T10:00:00Z','BTC',2,200)
        valid=convert_c('x1','2025-01-01T10:00:00Z','BTC',1,'ETH',10,500)
        motor,_,_=procesar_coinbase(self.csv('eur.csv',C,[orig,valid]))
        self.assertAlmostEqual(motor.resultados[0].ganancia_perdida,400)
        invalid=convert_c('x2','2025-01-01T10:00:00Z','BTC',1,'ETH',10,500,'USD')
        with self.assertRaisesRegex(FiscalImportError,'EUR'):
            procesar_coinbase(self.csv('usd.csv',C,[orig,invalid]))

    def test_r04_nonfinite_market_values_blocked(self):
        base=buy_c('b1','2023-01-01T10:00:00Z','BTC',2,200)
        for bad in ('Infinity','-Infinity','nan','1e309'):
            with self.subTest(value=bad):
                swap=convert_c('x1','2025-01-01T10:00:00Z','BTC',1,'ETH',10,bad)
                with self.assertRaises(FiscalImportError):
                    procesar_coinbase(self.csv('nonfinite.csv',C,[base,swap]))

    def test_r06_coinbase_mixed_iso_precision(self):
        base=buy_c('b1','2023-01-01T10:00:00Z','BTC',2,200)
        late=buy_c('b2','2024-01-01T10:00:00.900Z','BTC',1,300)
        sale=['s1','2025-01-01T10:00:00Z','Sell','BTC','1','EUR','500',
              '500','500','0','','','']
        motor,_,_=procesar_coinbase(self.csv('mixed.csv',C,[base,late,sale]))
        self.assertAlmostEqual(motor.resultados[0].precio_coste,100)
        self.assertAlmostEqual(motor.resultados[0].ganancia_perdida,400)

    def test_r07_uphold_gmt_offset_normalization(self):
        earlier=['Wed Jan 01 2025 00:00:00 GMT+0200',
                 'uphold','1','BTC','','','b2','credit-card','300','EUR',
                 'completed','in']
        later=['Tue Dec 31 2024 23:30:00 GMT+0000',
               'uphold','2','BTC','','','b1','credit-card','200','EUR',
               'completed','in']
        self.assertLess(ClasificadorUphold._parse_fecha_dt(earlier[0]),
                        ClasificadorUphold._parse_fecha_dt(later[0]))
        # The fiscal parser must preserve the true order, not strip GMT offsets.
        rows=[later,earlier]
        out=self.combined('uphold',U,[later],[earlier])
        full=self.csv('uphold_full.csv',U,rows)
        for path in (full,out):
            clasificador=ClasificadorUphold(path).clasificar()
            self.assertEqual(
                [x.importe for x in clasificador.compraventas[:2]],[300.0,200.0])

    def test_r03_backend_years_bitvavo_and_coinbase_timezone(self):
        view = inspect.unwrap(app.view_functions['api_fifo_anos'])
        first=buy_b('b1','2023-01-01','10:00:00',2,100)
        second=buy_b('b2','2025-01-01','10:00:00',1,300)
        csvpath=self.csv('years.csv',B,[first,second])
        body=pathlib.Path(csvpath).read_bytes()
        with app.test_request_context('/api/fifo/anos',method='POST',data={
            'exchange':'bitvavo','csv':(io.BytesIO(body),'years.csv')
        }):
            response=view()
            self.assertTrue(response.json['ok'])
            self.assertEqual(response.json['anos'],[2023,2025])
        # 00:30 +02:00 on 1 Jan is in the previous UTC tax year in this app.
        cb=buy_c('b1','2023-01-01T10:00:00Z','BTC',2,200)
        cs=['s1','2025-01-01T00:30:00+02:00','Sell','BTC','1','EUR','500',
            '500','500','0','','','']
        path=self.csv('offset.csv',C,[cb,cs])
        with app.test_request_context('/api/fifo/anos',method='POST',data={
            'exchange':'coinbase','csv':(io.BytesIO(pathlib.Path(path).read_bytes()),'offset.csv')
        }):
            response=view()
            self.assertTrue(response.json['ok'])
            self.assertEqual(response.json['anos'],[2023,2024])


if __name__ == '__main__':
    unittest.main()
