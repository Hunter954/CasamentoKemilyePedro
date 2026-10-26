"""Local headless UI validation with synthetic data; never connects to the VPS.
Run: python tests/browser_admin_experience.py (requires playwright and Chrome).
"""
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
artifacts = root / '.preview' / 'admin-experience'
artifacts.mkdir(parents=True, exist_ok=True)
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
from app import create_app, db
from app.models import AdminUser, SiteSettings, ContactLead, FAQ, GiftItem, GiftPurchase, GuestbookMessage, WhatsAppCampaign
from app.services.invitations import record_invitation_response
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect

app = create_app(); app.config.update(TESTING=True, SECRET_KEY='local-ui-test-only')
with app.app_context():
    db.drop_all(); db.create_all()
    admin = AdminUser(name='Administrador', email='local@example.test'); admin.set_password('local-only')
    db.session.add_all([admin, SiteSettings(couple_names='Kemily & Pedro')])
    contacts = []
    for i,(name,status,tag) in enumerate([('Ágata & Pedro','pending','Família'),('Bruna','yes','Família'),('Zélia & João','yes','Amigos'),('Carlos','no','Amigos')]):
        contact = ContactLead(name=name, phone=f'551199999123{i}', tag=tag, confirmation_code=f'12345{i}')
        db.session.add(contact); db.session.flush(); contacts.append(contact)
        if status != 'pending': record_invitation_response(contact,status, selected_names=['Zélia'] if i == 2 else None)
    gift = GiftItem(title='Jantar a dois', price=189.9, active=True); db.session.add(gift); db.session.flush()
    for i in range(6):
        db.session.add(GiftPurchase(gift=gift,buyer_name=['Ágata','Bruna','Zélia'][i%3],buyer_phone='5511999991234',buyer_email='guest@example.test',amount=100+i*20,status=['approved','pending','rejected'][i%3],message='Com muito carinho para vocês!'))
        db.session.add(GuestbookMessage(author_name=['Maria & José','Ana D’Ávila','Família Oliveira'][i%3],message=['Que essa nova fase seja cheia de amor, parceria e momentos inesquecíveis. Felicidades ao casal!','Foi lindo acompanhar essa história. Que venham muitos anos de alegria e cumplicidade!','Desejamos uma vida inteira de amor e sorrisos. Contem sempre com a gente.'][i%3],approved=i!=2))
        db.session.add(FAQ(question=['Qual o traje para o casamento?','Onde será a cerimônia?','Como confirmar minha presença?'][i%3],answer='Todas as informações estão disponíveis no convite e aqui no site. Esperamos vocês com muito carinho!',active=i!=2,position=i))
    db.session.add(WhatsAppCampaign(title='Convite oficial',message='Olá %contato%, confirme sua presença: %site_url%/?codigo=%codigo%',target_tag='todos'))
    db.session.add(WhatsAppCampaign(title='Lembrete de confirmação',message='Olá %contato%! Podemos contar com você?',target_tag='todos',target_rsvp='pending'))
    db.session.commit()
    cookie = app.session_interface.get_signing_serializer(app).dumps({'_user_id':admin.get_id(),'_fresh':True})

server = make_server('127.0.0.1',0,app,threaded=True)
thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
url = f'http://127.0.0.1:{server.server_port}'
try:
    with patch('app.admin.routes.get_instance_status',return_value={'connected':True}), sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome',headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        context.add_cookies([{'name':'session','value':cookie,'url':url}])
        page = context.new_page(); errors=[]; page.on('pageerror',lambda err:errors.append(str(err)))
        page.goto(url+'/admin/confirmacoes'); expect(page.locator('[data-filter-row]:visible')).to_have_count(4)
        page.locator('[data-filter-search]').fill('agata'); expect(page.locator('[data-filter-row]:visible')).to_have_count(1)
        page.locator('[data-filter-clear]').click()
        page.locator('[data-filter="status"]').select_option('yes'); expect(page.locator('[data-filter-row]:visible')).to_have_count(2)
        page.locator('[data-filter="status"]').select_option('partial'); expect(page.locator('[data-filter-row]:visible')).to_have_count(1)
        page.locator('[data-filter="tag"]').select_option('Família'); expect(page.locator('[data-filter-row]:visible')).to_have_count(0)
        expect(page.locator('[data-filter-empty]')).to_be_visible()
        page.locator('[data-filter-clear]').click(); page.locator('[data-filter-sort]').select_option('az')
        assert page.locator('[data-filter-row]').first.get_attribute('data-name') == 'Ágata & Pedro'
        with page.expect_download() as download: page.locator('[data-filter-export]').click()
        download.value.save_as(artifacts/'confirmacoes.csv')
        assert 'Ágata' in (artifacts/'confirmacoes.csv').read_text(encoding='utf-8-sig')
        page.locator('[data-filter-from]').fill('2099-01-01'); expect(page.locator('[data-filter-row]:visible')).to_have_count(0)
        page.locator('[data-filter-clear]').click()
        for path,name in [('/admin/confirmacoes','confirmacoes'),('/admin/compras','compras'),('/admin/mural','mural-admin'),('/admin/perguntas-frequentes','faq'),('/admin/campanhas','campanhas'),('/mural','mural-publico')]:
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000}); page.goto(url+path); page.locator('h1').first.wait_for()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (path,width,'horizontal overflow')
                page.screenshot(path=str(artifacts/f'{name}-{width}.png'),full_page=True)
        page.goto(url+'/admin/campanhas?audience=pending&new=1')
        expect(page.locator('#campaign-dialog')).to_be_visible(); expect(page.locator('[data-campaign-audience]')).to_have_value('pending')
        page.locator('[data-close-dialog]').click()
        page.locator('[data-new-reminder]').click(); expect(page.locator('[data-campaign-audience]')).to_have_value('pending')
        page.locator('[data-close-dialog]').click()
        page.locator('a[href="/admin/campanhas/2/publico"]').click()
        expect(page.locator('[data-filter-row]')).to_have_count(1)
        page.goto(url+'/admin/compras'); page.locator('[data-filter="status"]').select_option('approved')
        expect(page.locator('[data-filter-row]:visible')).to_have_count(2)
        page.locator('[data-filter-sort]').select_option('high')
        assert page.locator('[data-filter-row]:visible').first.get_attribute('data-amount') == '160.0'
        assert not errors, errors
        browser.close()
    print('Browser checks passed: filters, sorting, CSV, reminder audience, all 6 pages at 1440px and 390px.')
finally:
    server.shutdown()
