"""Reproductions of F01-F07 found by the independent audit (synthetic data).

These run against fiscal parsers and FIFO, not a mocked computation. Files and
values are fabricated; no real client data is required.
"""
import csv
import pathlib
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import procesar_bitvavo, procesar_coinbase, procesar_kraken, _pipeline_motor
from clasificador_binance_tx import ClasificadorBinanceTx
from clasificador_cryptocom import ClasificadorCryptoCom
from clasificador_bitget import ClasificadorBitget
from motor_fifo import MotorFIFO

COINBASE = ['ID','Timestamp','Transaction Type','Asset','Quantity Transacted',
            'Price Currency','Price at Transaction','Subtotal',
            'Total (inclusive of fees and/or spread)','Fees and/or Spread',
            'Notes','Sender Address','Recipient Address']
BITVAVO = ['Timezone','Date','Time','Type','Currency','Amount','Quote Currency',
           'Quote Price','Received / Paid Currency','Received / Paid Amount',
           'Fee currency','Fee amount','Status','Transaction ID','Address']
KRAKEN = ['txid','refid','time','type','subtype','aclass','subclass','asset',
          'wallet','amount','fee','balance']


def cb(uid, date, kind, coin, quantity, total, currency='EUR', notes=''):
    return [uid,date,kind,coin,str(quantity),currency,'100',str(total),
            str(total),'0',notes,'','']


class FiscalIntegrityF01F07(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d=pathlib.Path(t.name)

    def save(self, name, columns, rows):
        p=self.d/name
        with p.open("w",encoding="utf-8",newline="") as f:
            w=csv.writer(f)
            w.writerow(columns);w.writerows(rows)
        return str(p)

    def test_f01_aggregate_micro_lots_and_cost(self):
        m=MotorFIFO()
        for day in range(1,21):
            m.registrar_compra(
                fecha=f"2023-01-{day:02} 10:00:00",activo="BTC",
                cantidad=0.00005,importe=5,contraparte="EUR",
                fee_activo="EUR",fee_cantidad=0)
        pos=m.posicion_actual()
        self.assertEqual(len(pos),1)
        self.assertAlmostEqual(pos[0].cantidad_total,0.001,places=10)
        self.assertAlmostEqual(pos[0].coste_total,100)
        m.registrar_venta(
            fecha="2025-01-01",activo="BTC",cantidad=0.0005,
            importe=100,contraparte="EUR",fee_activo="EUR",fee_cantidad=0)
        self.assertAlmostEqual(m.resultados[0].precio_coste,50)
        self.assertAlmostEqual(m.posicion_actual()[0].cantidad_total,0.0005,places=10)

    def test_f01_small_missing_inventory_must_flag(self):
        m=MotorFIFO()
        m.registrar_compra("2023-01-01","BTC",0.00005,5,"EUR","EUR",0)
        m.registrar_venta("2025-01-01","BTC",0.0001,20,"EUR","EUR",0)
        self.assertTrue(m.resultados[0].inventario_incompleto)
        self.assertTrue(any("insuficiente" in text for text in m.advertencias))

    def test_f02_coinbase_income_enters_fifo_once(self):
        rows=[
            cb("b1","2023-01-01T10:00:00Z","Buy","ETH",1,50),
            cb("r1","2024-01-01T10:00:00Z","Staking Income","ETH",1,100),
            cb("s1","2025-01-01T10:00:00Z","Sell","ETH",2,400),
        ]
        m,r,_=procesar_coinbase(self.save("coinbase-income.csv",COINBASE,rows))
        self.assertEqual(len(r),1)
        self.assertEqual(len(m.resultados),1)
        self.assertAlmostEqual(m.resultados[0].precio_coste,150)
        self.assertAlmostEqual(m.resultados[0].ganancia_perdida,250)
        self.assertFalse(m.resultados[0].inventario_incompleto)

    def test_f02_bitvavo_staking_enters_fifo_once(self):
        rows=[
            ['UTC','2023-01-01','10:00:00','buy','ETH','1','EUR','50',
             'EUR','-50','EUR','0','Completed','b1',''],
            ['UTC','2024-01-01','10:00:00','staking','ETH','1','EUR','100',
             'EUR','0','EUR','0','Completed','r1',''],
            ['UTC','2025-01-01','10:00:00','sell','ETH','-2','EUR','200',
             'EUR','400','EUR','0','Completed','s1',''],
        ]
        m,r,_=procesar_bitvavo(self.save("bitvavo-income.csv",BITVAVO,rows))
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(m.resultados[0].precio_coste,150)
        self.assertAlmostEqual(m.resultados[0].ganancia_perdida,250)

    def test_f02_unvalued_coinbase_reward_fails_closed(self):
        rows=[cb('r1','2025-01-01T10:00:00Z','Staking Income','ETH',1,0)]
        with self.assertRaisesRegex(ValueError,"Datos fiscales no seguros"):
            procesar_coinbase(self.save("unvalued.csv",COINBASE,rows))

    def test_f03_bitget_fee_in_base_deducts_received_units(self):
        c=ClasificadorBitget.__new__(ClasificadorBitget)
        c.compraventas=[];c.desconocidas=[];c._tiene_pares_usdt=False
        c._procesar_fila_detalles({
            "Date":"2023-01-01 10:00:00","Base Asset":"BTC","Quote Asset":"EUR",
            "Direction":"BUY","Amount":"2","Total":"200",
            "Fee":"0.02","Fee Coin":"BTC"
        })
        self.assertEqual(len(c.compraventas),1)
        self.assertAlmostEqual(c.compraventas[0].cantidad,1.98)
        m=MotorFIFO()
        for op in c.compraventas:
            m.registrar_compra(op.fecha,op.activo,op.cantidad,op.importe,
                              op.contraparte,op.fee_activo,op.fee_cantidad)
        m.registrar_venta("2025-01-01","BTC",1.98,396,"EUR","EUR",0)
        self.assertAlmostEqual(m.resultados[0].precio_coste,200)
        self.assertAlmostEqual(m.resultados[0].ganancia_perdida,196)
        self.assertFalse(m.posicion_actual())

    def test_f03_bitget_fee_in_quote_does_not_reduce_received_units(self):
        c=ClasificadorBitget.__new__(ClasificadorBitget)
        c.compraventas=[];c.desconocidas=[];c._tiene_pares_usdt=False
        c._procesar_fila_detalles({
            "Date":"2023-01-01 10:00:00","Base Asset":"BTC","Quote Asset":"EUR",
            "Direction":"BUY","Amount":"2","Total":"200","Fee":"1","Fee Coin":"EUR"
        })
        self.assertAlmostEqual(c.compraventas[0].cantidad,2)

    def test_f04_coinbase_usd_usdt_usdc_buys_rejected(self):
        for unit in ("USD","USDT","USDC"):
            with self.subTest(unit=unit):
                rows=[cb('b1','2023-01-01T10:00:00Z','Buy','BTC',2,200,unit)]
                with self.assertRaisesRegex(ValueError,"no en EUR"):
                    procesar_coinbase(self.save('unit.csv',COINBASE,rows))

    def test_f04_coinbase_eur_valid_gain_unchanged(self):
        rows=[cb('b1','2023-01-01T10:00:00Z','Buy','BTC',2,200),
              cb('s1','2025-01-01T10:00:00Z','Sell','BTC',1,500)]
        m,_,_=procesar_coinbase(self.save('eur.csv',COINBASE,rows))
        self.assertAlmostEqual(m.resultados[0].precio_coste,100)
        self.assertAlmostEqual(m.resultados[0].ganancia_perdida,400)

    def test_f05_coinbase_invalid_numeric_rejected(self):
        for column,bad in [(8,'broken'),(8,'Infinity'),(8,'1e309'),(4,'NaN'),(4,'Infinity')]:
            with self.subTest(column=column,bad=bad):
                rows=[cb('b1','2023-01-01T10:00:00Z','Buy','BTC',2,200)]
                rows[0][column]=bad
                with self.assertRaisesRegex(ValueError,"Datos fiscales no seguros"):
                    procesar_coinbase(self.save('invalid.csv',COINBASE,rows))

    def test_f06_kraken_missing_leg_rejected(self):
        rows=[
            ['a','a','2023-01-01 10:00:00','spend','','currency','','EUR','spot','-200','0','0'],
            ['b','a','2023-01-01 10:00:00','receive','','currency','','BTC','spot','2','0','0'],
            ['c','s','2025-01-01 10:00:00','spend','','currency','','BTC','spot','-1','0','0']
        ]
        with self.assertRaisesRegex(ValueError,"patas spend/receive"):
            procesar_kraken(self.save('missing.csv',KRAKEN,rows))

    def test_f06_kraken_trade_type_rejected(self):
        rows=[['a','a','2025-01-01 10:00:00','trade','','currency','','BTC',
               'spot','-1','0','0']]
        with self.assertRaisesRegex(ValueError,"trade"):
            procesar_kraken(self.save('trade.csv',KRAKEN,rows))

    def test_f07_binance_multi_spends_same_second_rejected(self):
        c=ClasificadorBinanceTx.__new__(ClasificadorBinanceTx)
        c.df=pd.DataFrame([
            {'Tiempo':pd.Timestamp('2025-01-01 10:00:00'), 'Operación':'Transaction Spend','Moneda':'EUR','Cambio':-100.0,'Cuenta':'Spot','Observación':''},
            {'Tiempo':pd.Timestamp('2025-01-01 10:00:00'), 'Operación':'Transaction Spend','Moneda':'USDT','Cambio':-100.0,'Cuenta':'Spot','Observación':''},
            {'Tiempo':pd.Timestamp('2025-01-01 10:00:00'), 'Operación':'Transaction Buy','Moneda':'BTC','Cambio':2.0,'Cuenta':'Spot','Observación':''},
        ])
        c._procesadas=set();c.compraventas=[];c.swaps=[];c.movimientos=[];c.desconocidas=[]
        with self.assertRaisesRegex(ValueError,"correspondencia verificable"):
            c._procesar_transaction_buy_spend()

    def test_f07_cryptocom_multi_debit_same_time_rejected(self):
        c=ClasificadorCryptoCom.__new__(ClasificadorCryptoCom)
        date=pd.Timestamp("2025-01-01 10:00:00")
        c.df=pd.DataFrame([
            {'Timestamp (UTC)':date,'Transaction Kind':'dust_conversion_debited','Currency':'BTC','Amount':-1},
            {'Timestamp (UTC)':date,'Transaction Kind':'dust_conversion_debited','Currency':'ETH','Amount':-1},
            {'Timestamp (UTC)':date,'Transaction Kind':'dust_conversion_credited','Currency':'SOL','Amount':2},
        ])
        c.swaps=[]
        with self.assertRaisesRegex(ValueError,"varias patas"):
            c._procesar_swaps()


if __name__=="__main__":
    unittest.main()
