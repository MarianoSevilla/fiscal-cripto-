"""U04 real Chromium UI, local files and synthetic API. No provider calls."""
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from qa_responsive_nav import server, PAGES

PAGES.update({'/pagar/U04':'pagar.html','/admin/asesoramiento':'admin-asesoramiento.html'})
ATTEMPT='00000000-0000-4000-8000-000000000004'
MESSAGE='Estamos comprobando el resultado de tu pago con PayPal. No realices otro pago. Conservamos tu solicitud y te informaremos cuando la comprobación termine.'

def main():
    with server() as base, sync_playwright() as p:
        browser=p.chromium.launch()
        for width in (375,768,1280):
            page=browser.new_page(viewport={'width':width,'height':900})
            errors=[];posts=[];state={'value':'UNCERTAIN'}
            page.on('pageerror',lambda e:errors.append(str(e)))
            def api(route):
                req=route.request;path=urlsplit(req.url).path
                if req.method=='POST':
                    posts.append((path,req.headers.get('x-u04-csrf')))
                    assert path.endswith('/consultar') and req.headers.get('x-u04-csrf')=='synthetic-csrf'
                    state['value']='RECONCILED';data={'state':'RECONCILED'}
                elif path=='/api/me':
                    data={'user':{'id':1,'full_name':'Synthetic Admin','email':'owner@example.invalid','is_admin':True,'is_fiscal_advisor':True,'role':'admin'}}
                elif path.startswith('/api/pago/info/'):
                    data={'state':'reconciliation_pending','message':MESSAGE}
                elif path.endswith('/paypal'):
                    data={'hold':False,'generation':ATTEMPT,'csrf_token':'synthetic-csrf','writes_enabled':False,'attempts':[{
                        'id':ATTEMPT,'origin':'managed','state':state['value'],'paypal_order_id':'ORDERUI04',
                        'paypal_capture_id':None,'quote_generation':ATTEMPT,'quoted_amount_cents':10001,
                        'created_at':'2026-10-11T12:00:00Z','last_observed_at':None,'capture_started_at':'2026-10-11T12:00:01Z',
                        'customer_notification_state':'UNCLAIMED','owner_notification_state':'UNCLAIMED','events':[]} ]}
                elif path.endswith('/solicitudes/4'):
                    data={'id':4,'full_name':'Synthetic','email':'synthetic@example.invalid','status':'quote_sent',
                          'service_type':'revision_basica','tax_year':2026,'case_description':'Synthetic only','notes':[],
                          'created_at':'2026-10-11T12:00:00Z','history':[],'files':[]}
                elif '/solicitudes' in path:data=[]
                else:data={}
                route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
            page.route('**/api/**',api)
            page.route('https://**/*',lambda route:route.abort())
            page.goto(base+'/pagar/U04')
            page.locator('#stateReconciliation').wait_for(state='visible')
            assert page.locator('#reconciliationMessage').inner_text()==MESSAGE
            assert not page.locator('#payBtn').is_visible() and not posts
            page.goto(base+'/admin/asesoramiento')
            page.wait_for_function("typeof u04Action === 'function' && typeof openDetail === 'function' && _currentUser?.is_admin")
            page.evaluate('openDetail(4)')
            button=page.get_by_role('button',name='Consultar en PayPal',exact=True)
            button.wait_for(state='visible')
            button.click()
            page.wait_for_function("document.getElementById('detailPanel').textContent.includes('RECONCILED')")
            assert posts==[('/api/admin/paypal/attempts/'+ATTEMPT+'/consultar','synthetic-csrf')]
            assert not errors,errors
            assert page.locator('#filterFinancial').count()==1
            page.close()
        browser.close()
    print('U04 Chromium: pending hides payment; CSRF GET-only reconciliation action; no JS errors at 375/768/1280 PASS')

if __name__=='__main__':main()
