"""Model 721 regression: same valid Bitvavo input must keep BTC and ETH holdings.

No network, personal CSV or external prices; tests shared FIFO/parser contract.
"""
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from app import procesar_bitvavo
from modelo721 import generar_datos_modelo_721
from datetime import datetime

BITVAVO_CSV=(
"Timezone,Date,Time,Type,Currency,Amount,Quote Currency,Quote Price,"
"Received / Paid Currency,Received / Paid Amount,Fee currency,Fee amount,Status,Transaction ID,Address\n"
"UTC,2024-03-15,12:00:00,buy,BTC,0.05,EUR,60000,EUR,-3000,EUR,2,Completed,tx001,\n"
"UTC,2024-07-20,14:00:00,buy,ETH,1.0,EUR,3200,EUR,-3200,EUR,3,Completed,tx002,\n"
)

class Model721BitvavoRegression(unittest.TestCase):
    def test_bitvavo_holdings_survive_fifo_and_721_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'bitvavo.csv'
            p.write_text(BITVAVO_CSV,encoding='utf-8')
            motor,_,clasificador=procesar_bitvavo(str(p))
            ops=[(op.activo,op.cantidad) for op in clasificador.compraventas]
            self.assertEqual(len(ops),2,f'Parser trades: {ops!r}; warnings: {motor.advertencias!r}')
            snapshot=motor.posicion_a_fecha(datetime(2024,12,31,23,59,59))
            self.assertEqual({x.activo for x in snapshot},{'BTC','ETH'},
                             f'Internal lots: {dict(motor.inventario)!r}; '
                             f'parser operations: {[(x.tipo, x.activo, x.cantidad, x.importe) for x in clasificador.compraventas]!r}; '
                             f'warnings: {motor.advertencias!r}')
            data=generar_datos_modelo_721(motor,'bitvavo',2024)
            assets={a['activo'] for exchange in data['exchanges'] for a in exchange.get('activos',[])}
            self.assertEqual(assets,{'BTC','ETH'},f'721 exchanges: {data["exchanges"]!r}')

if __name__=='__main__':
    unittest.main()
