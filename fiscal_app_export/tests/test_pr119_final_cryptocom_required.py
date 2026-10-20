"""Final A01 regression: absent fiscal quantities and IBAN costs are not zero.

Synthetic CSV only; preserve empty optional To Amount and Native Amount fields.
"""
import csv
import pytest
from clasificador_cryptocom import ClasificadorCryptoCom

HEADER = ['Timestamp (UTC)', 'Transaction Description', 'Currency', 'Amount',
          'To Currency', 'To Amount', 'Native Currency', 'Native Amount',
          'Native Amount (in USD)', 'Transaction Kind', 'Transaction Hash']

def write(tmp_path, row, missing=None):
    header = [key for key in HEADER if key != missing]
    path = tmp_path / 'synthetic.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerow({key: row.get(key, '') for key in header})
    return str(path)

def row(kind='crypto_purchase'):
    return dict(zip(HEADER, ['2024-01-01 10:00:00', 'Synthetic', 'BTC', '2',
                            '', '', 'EUR', '200', '', kind, 'synthetic-id']))

@pytest.mark.parametrize('kind,field', [
    ('crypto_purchase', 'Amount'),
    ('trading.crypto_purchase.google_pay', 'Amount'),
    ('crypto_viban_exchange', 'Amount'),
    ('viban_purchase', 'Amount'),
    ('viban_purchase', 'To Amount'),
    ('trading.limit_order.cash_account.purchase_commit', 'Amount'),
    ('trading.limit_order.cash_account.purchase_commit', 'To Amount'),
    ('crypto_earn_interest_paid', 'Amount'),
    ('finance.dpos.non_compound_interest.crypto_wallet', 'Amount'),
    ('campaign_reward', 'Amount'),
    ('rewards_platform_deposit_credited', 'Amount'),
    ('reward.synthetic', 'Amount'),
])
@pytest.mark.parametrize('absent_column', [False, True])
def test_missing_required_fiscal_field_is_rejected(tmp_path, kind, field, absent_column):
    data = row(kind)
    if 'purchase' in kind and kind not in ('crypto_purchase', 'trading.crypto_purchase.google_pay'):
        data.update({'Currency': 'EUR', 'Amount': '-200', 'To Currency': 'BTC',
                     'To Amount': '2', 'Native Amount': ''})
    if kind == 'crypto_viban_exchange':
        data['Amount'] = '-1'
    data[field] = ''
    with pytest.raises(ValueError, match='Datos fiscales no seguros'):
        ClasificadorCryptoCom(write(tmp_path, data, field if absent_column else None)).clasificar()

def test_iban_missing_fallback_eur_amount_rejected(tmp_path):
    data = row('viban_purchase')
    data.update({'Currency': 'USD', 'Amount': '-210', 'To Currency': 'BTC',
                 'To Amount': '2', 'Native Amount': ''})
    with pytest.raises(ValueError, match='Datos fiscales no seguros'):
        ClasificadorCryptoCom(write(tmp_path, data)).clasificar()

def test_optional_fields_stay_optional_and_numeric_zero_is_not_missing(tmp_path):
    data = row()
    c = ClasificadorCryptoCom(write(tmp_path, data)).clasificar()
    assert [(op.cantidad, op.importe) for op in c.compraventas] == [(2.0, 200.0)]
    data.update({'Transaction Kind': 'viban_purchase', 'Currency': 'EUR',
                 'Amount': '-200', 'To Currency': 'BTC', 'To Amount': '2',
                 'Native Amount': ''})
    c = ClasificadorCryptoCom(write(tmp_path, data)).clasificar()
    assert [(op.cantidad, op.importe) for op in c.compraventas] == [(2.0, 200.0)]
    assert ClasificadorCryptoCom._float('0', required=True) == 0.0
