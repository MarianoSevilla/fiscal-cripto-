"""F01-F07 closure counterexamples from Work, all with synthetic financial data."""
import csv
import math
import pathlib
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import procesar_coinbase, procesar_bitvavo, _motor_a_json
from motor_fifo import MotorFIFO
from clasificador_bitget import ClasificadorBitget, ClasificadorBitgetMulti
from clasificador_cryptocom import ClasificadorCryptoCom
from clasificador_coinbase import ClasificadorCoinbase

COINBASE = ['ID','Timestamp','Transaction Type','Asset','Quantity Transacted',
            'Price Currency','Price at Transaction','Subtotal',
            'Total (inclusive of fees and/or spread)','Fees and/or Spread',
            'Notes','Sender Address','Recipient Address']
BITVAVO = ['Timezone','Date','Time','Type','Currency','Amount','Quote Currency',
           'Quote Price','Received / Paid Currency','Received / Paid Amount',
           'Fee currency','Fee amount','Status','Transaction ID','Address']


class FiscalClosureRound2(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d=pathlib.Path(t.name)

    def csv(self, name, header, rows):
        p=self.d/name
        with p.open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        return str(p)

    def test_f02_coinbase_subseconds_ordered_economically(self):
        base=['b1','2023-01-01T10:00:00Z','Buy','ETH','1','EUR','50','50','50','0','','','']
        reward=['r1','2025-01-01T10:00:00.100Z','Staking Income','ETH','1','EUR','100','100','100','0','','','']
        sell=['s1','2025-01-01T10:00:00.900Z','Sell','ETH','2','EUR','200','400','400','0','','','']
        for i,rows in enumerate(([base,reward,sell],[base,sell,reward])):
            with self.subTest(order=i):
                m,_,_=procesar_coinbase(self.csv(f'cb{i}.csv',COINBASE,rows))
                self.assertAlmostEqual(m.resultados[0].precio_coste,150)
                self.assertAlmostEqual(m.resultados[0].ganancia_perdida,250)
                self.assertFalse(m.posicion_actual())

    def test_f02_bitvavo_subseconds_ordered_economically(self):
        base=['UTC','2023-01-01','10:00:00','buy','ETH','1','EUR','50','EUR','-50','EUR','0','Completed','b1','']
        reward=['UTC','2025-01-01','10:00:00.100','staking','ETH','1','EUR','100','EUR','0','EUR','0','Completed','r1','']
        sale=['UTC','2025-01-01','10:00:00.900','sell','ETH','-2','EUR','200','EUR','400','EUR','0','Completed','s1','']
        for i,rows in enumerate(([base,reward,sale],[base,sale,reward])):
            m,_,_=procesar_bitvavo(self.csv(f'bv{i}.csv',BITVAVO,rows))
            self.assertAlmostEqual(m.resultados[0].precio_coste,150)
            self.assertAlmostEqual(m.resultados[0].ganancia_perdida,250)
            self.assertFalse(m.posicion_actual())

    def test_f02_very_small_positive_bitvavo_reward_basis(self):
        reward=['UTC','2025-01-01','10:00:00','staking','ETH','0.00000001','EUR','100','EUR','0','EUR','0','Completed','r1','']
        m,r,_=procesar_bitvavo(self.csv('tiny.csv',BITVAVO,[reward]))
        self.assertAlmostEqual(r[0].valor_eur,0.000001,places=12)
        self.assertAlmostEqual(m.posicion_actual()[0].cantidad_total,1e-8,places=14)

    def test_f05_coinbase_valid_scientific_notation_not_corrupted(self):
        row=['b1','2023-01-01T10:00:00Z','Buy','BTC','2','EUR','0.01','0.02','€2e-2','0','','','']
        sale=['s1','2025-01-01T10:00:00Z','Sell','BTC','1','EUR','500','500','500','0','','','']
        m,_,_=procesar_coinbase(self.csv('scientific.csv',COINBASE,[row,sale]))
        self.assertAlmostEqual(m.resultados[0].precio_coste,0.01)
        self.assertAlmostEqual(m.resultados[0].ganancia_perdida,499.99)

    def test_f05_coinbase_infinite_convert_notes_rejected(self):
        base=['b1','2023-01-01T10:00:00Z','Buy','BTC','2','EUR','100','200','200','0','','','']
        convert=['x1','2025-01-01T10:00:00Z','Convert','BTC','1','EUR','500','500','500','0',
                 'Converted 1 BTC to '+('9'*310)+' ETH','','']
        with self.assertRaisesRegex(ValueError,'no seguros'):
            procesar_coinbase(self.csv('huge.csv',COINBASE,[base,convert]))

    def test_f05_engine_overflow_is_rejected(self):
        m=MotorFIFO()
        with self.assertRaisesRegex(ValueError,'no seguros'):
            m.registrar_compra('2023-01-01','BTC',1e-308,1e308,'EUR','EUR',0)
        for bad in (float('inf'),float('nan')):
            with self.assertRaisesRegex(ValueError,'no seguros'):
                m.registrar_compra('2023-01-01','BTC',1,bad,'EUR','EUR',0)

    def test_f01_positive_submicro_json_position(self):
        m=MotorFIFO()
        m.registrar_compra('2025-01-01','BTC',4e-7,0.04,'EUR','EUR',0)
        _,position,_=_motor_a_json(m)
        self.assertEqual(position[0]['cantidad'],4e-7)

    def test_f03_bitget_quote_fee_increases_eur_cost(self):
        c=ClasificadorBitget.__new__(ClasificadorBitget)
        c.compraventas=[];c.desconocidas=[];c._tiene_pares_usdt=False
        c._procesar_fila_detalles({
            'Date':'2023-01-01 10:00:00','Base Asset':'BTC','Quote Asset':'EUR',
            'Direction':'BUY','Amount':'2','Total':'200','Fee':'1','Fee Coin':'EUR'
        })
        m=MotorFIFO()
        op=c.compraventas[0]
        m.registrar_compra(op.fecha,op.activo,op.cantidad,op.importe,op.contraparte,op.fee_activo,op.fee_cantidad)
        m.registrar_venta('2025-01-01','BTC',2,500,'EUR','EUR',3)
        self.assertAlmostEqual(m.resultados[0].precio_coste,201)
        self.assertAlmostEqual(m.resultados[0].ganancia_perdida,296)

    def test_f03_bitget_fee_in_third_currency_fails_closed(self):
        c=ClasificadorBitget.__new__(ClasificadorBitget)
        c.compraventas=[];c.desconocidas=[];c._tiene_pares_usdt=False
        with self.assertRaisesRegex(ValueError,'tercera moneda'):
            c._procesar_fila_detalles({
                'Date':'2023-01-01 10:00:00','Base Asset':'BTC','Quote Asset':'EUR',
                'Direction':'BUY','Amount':'2','Total':'200','Fee':'0.1','Fee Coin':'BGB'})

    def test_f03_bitget_atomic_on_bad_second_file(self):
        header=['Date','Trading pair','Base Asset','Quote Asset','Direction',
                'Price','Amount','Total','Fee','Fee Coin']
        good=['2023-01-01 10:00:00','BTCEUR','BTC','EUR','BUY','100','2','200','0','EUR']
        bad=['2025-01-01 10:00:00','BTCEUR','BTC','EUR','BUY','100','2','200','3','BTC']
        first=self.csv('valid.csv',header,[good])
        second=self.csv('unsafe.csv',header,[bad])
        with self.assertRaisesRegex(ValueError,'Datos fiscales no seguros'):
            ClasificadorBitgetMulti([first,second],['valid.csv','unsafe.csv']).clasificar()

    def test_f03_order_number_different_fills_preserved(self):
        c=ClasificadorBitgetMulti([])
        from clasificador_bitget import OperacionCompraventa
        rows=[]
        for i in (1,2):
            rows.append(OperacionCompraventa(
                fecha=f'2023-01-0{i} 10:00:00',tipo='COMPRA',
                activo='BTC',cantidad=0.99,contraparte='EUR',
                importe=100,fee_activo='BTC',fee_cantidad=0.01,order_id='order-1'))
        self.assertEqual(len(c._dedup_intra_spot_trading(rows)),2)

    def test_f07_crypto_orphan_swap_not_silent(self):
        for kind,amount in (('dust_conversion_debited',-1),
                            ('dust_conversion_credited',1)):
            c=ClasificadorCryptoCom.__new__(ClasificadorCryptoCom)
            c.df=pd.DataFrame([{'Timestamp (UTC)':pd.Timestamp('2025-01-01'),
                                'Transaction Kind':kind,'Currency':'ETH','Amount':amount}])
            c.swaps=[]
            with self.assertRaisesRegex(ValueError,'contraparte'):
                c._procesar_swaps()

    def test_f07_crypto_homogeneous_multiple_fills_aggregate(self):
        ts=pd.Timestamp('2025-01-01 10:00:00')
        c=ClasificadorCryptoCom.__new__(ClasificadorCryptoCom)
        c.df=pd.DataFrame([
            {'Timestamp (UTC)':ts,'Transaction Kind':'dust_conversion_debited','Currency':'BTC','Amount':-0.5},
            {'Timestamp (UTC)':ts,'Transaction Kind':'dust_conversion_debited','Currency':'BTC','Amount':-0.5},
            {'Timestamp (UTC)':ts,'Transaction Kind':'dust_conversion_credited','Currency':'ETH','Amount':2}
        ])
        c.swaps=[]
        self.assertEqual(len(c._procesar_swaps()),3)
        self.assertEqual(len(c.swaps),1)
        self.assertEqual(c.swaps[0].cantidad_entregada,1)
        self.assertEqual(c.swaps[0].cantidad_recibida,2)

    def test_f03_bitget_spot_and_ledger_same_net_fill_not_duplicated(self):
        from clasificador_bitget import OperacionCompraventa
        def operation(quantity):
            return OperacionCompraventa(
                fecha='2023-01-01 10:00:00',tipo='COMPRA',
                activo='BTC',cantidad=quantity,contraparte='USDT',
                importe=200,fee_activo='BTC',fee_cantidad=0.02)
        c=ClasificadorBitgetMulti([])
        c._cv_por_fuente={'spot_trading':[operation(1.98)],
                          'transacciones':[operation(1.98)],'detalles':[]}
        c._consolidar_compraventas()
        self.assertEqual(len(c.compraventas),1)
        self.assertEqual(c.compraventas[0].cantidad,1.98)

    def test_f05_cross_exchange_nonfinite_raw_numbers_rejected(self):
        from clasificador_bitvavo import ClasificadorBitvavo
        from clasificador_uphold import ClasificadorUphold
        from clasificador_cryptocom import ClasificadorCryptoCom
        from clasificador_binance_tx import ClasificadorBinanceTx
        bitvavo=['UTC','2025-01-01','10:00:00','buy','BTC','Infinity','EUR','100',
                 'EUR','-100','EUR','0','Completed','b1','']
        with self.assertRaisesRegex(ValueError,'no seguros'):
            procesar_bitvavo(self.csv('bv-inf.csv',BITVAVO,[bitvavo]))
        with self.assertRaisesRegex(ValueError,'no seguros'):
            ClasificadorUphold._float('Infinity')
        with self.assertRaisesRegex(ValueError,'no seguros'):
            ClasificadorCryptoCom._float('Infinity')
        with self.assertRaisesRegex(ValueError,'no seguros'):
            ClasificadorBitget._procesar_fila_detalles(
                self._bitget_stub(), {
                    'Date':'2023-01-01 10:00:00','Base Asset':'BTC','Quote Asset':'EUR',
                    'Direction':'BUY','Amount':'Infinity','Total':'200','Fee':'0',
                    'Fee Coin':'EUR'})
        # Raw parsed BTC spend cannot survive Binance's numeric preflight.
        from clasificador_binance_tx import ClasificadorBinanceTx
        path=self.csv('binance-inf.csv',
                      ['Tiempo','Cuenta','Operación','Moneda','Cambio','Observación'],
                      [['2025-01-01 10:00:00','Spot','Transaction Spend',
                        'BTC','-Infinity','']])
        with self.assertRaises(ValueError):
            ClasificadorBinanceTx(path)

    @staticmethod
    def _bitget_stub():
        stub=ClasificadorBitget.__new__(ClasificadorBitget)
        stub.compraventas=[]
        stub.desconocidas=[]
        stub._tiene_pares_usdt=False
        return stub

    def test_f01_tiny_pdf_formatter_not_zero(self):
        from generador_pdf import _fmt_cantidad
        self.assertNotEqual(_fmt_cantidad(0.0000004),'0.000000')
        self.assertIn('0.0000004',_fmt_cantidad(0.0000004))

if __name__ == '__main__':
    unittest.main()
