import os
import unittest
from datetime import datetime
from unittest.mock import patch, Mock
from sqlalchemy import text, inspect
os.environ['DATABASE_URL']='sqlite:///:memory:'
from app import create_app, db, _sync_schema
from app.models import GiftItem, GiftPurchase, GuestbookMessage, SiteSettings, ContactLead, RSVP
from app.services.mercado_pago import MercadoPagoService
from app.services.payment_status import apply_verified_payment
from app.services.guestbook import import_existing_messages


class PaymentAndGuestbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app()
        cls.app.config.update(TESTING=True,SECRET_KEY='payment-tests',MERCADO_PAGO_ACCESS_TOKEN='')

    def setUp(self):
        self.context=self.app.app_context();self.context.push()
        db.drop_all();db.create_all()
        self.settings=SiteSettings(mercado_pago_enabled=True,mercado_pago_access_token='test-only-token',require_guestbook_approval=True)
        self.gift=GiftItem(title='Jantar',price=189.90,active=True)
        db.session.add_all([self.settings,self.gift]);db.session.commit()
        self.purchase=GiftPurchase(gift_id=self.gift.id,buyer_name='Maria Silva',buyer_email='test@example.test',buyer_phone='11999991234',message='Felicidades ao casal!',amount=189.90,status='pending')
        db.session.add(self.purchase);db.session.commit()
        self.client=self.app.test_client()

    def tearDown(self):
        db.session.remove();self.context.pop()

    def payment(self,**overrides):
        result={'id':183514745868,'external_reference':str(self.purchase.id),'status':'pending',
                'currency_id':'BRL','transaction_amount':189.90,'payment_method_id':'bolbradesco'}
        result.update(overrides);return result

    def callback(self,path='success',payment=None,query=''):
        with patch.object(MercadoPagoService,'fetch_payment',return_value=payment or self.payment()):
            return self.client.get(f'/checkout/{path}?payment_id=183514745868&status=pending&external_reference=999{query}')

    def webhook(self,payment=None,**kwargs):
        with patch.object(MercadoPagoService,'fetch_payment',return_value=payment or self.payment()):
            return self.client.post('/api/mercado-pago/webhook?external_reference=999',json={'type':'payment','data':{'id':183514745868}},**kwargs)

    def test_boleto_pending_on_success_path_does_not_show_approval(self):
        html=self.callback(query='&payment_type=ticket').get_data(as_text=True)
        self.assertIn('Aguardando pagamento',html)
        self.assertIn('Seu boleto foi gerado',html)
        self.assertNotIn('Pagamento aprovado',html)
        self.assertEqual(self.purchase.status,'pending')
        self.assertTrue(self.purchase.payment_verified)
        self.assertEqual(GuestbookMessage.query.count(),0)

    def test_url_success_and_status_approved_cannot_forge_payment(self):
        for url in ('/checkout/success','/checkout/success?status=approved&external_reference=1','/checkout/success?payment_id=123&status=approved'):
            with patch.object(MercadoPagoService,'fetch_payment',return_value={}):
                html=self.client.get(url).get_data(as_text=True)
            self.assertNotIn('Pagamento aprovado',html)
        self.assertEqual(self.purchase.status,'pending')

    def test_only_verified_approval_shows_success_even_on_failure_path(self):
        response=self.callback(path='failure',payment=self.payment(status='approved'))
        self.assertIn('Pagamento aprovado',response.get_data(as_text=True))
        self.assertEqual(self.purchase.status,'approved')
        self.assertTrue(self.purchase.payment_verified)
        self.assertEqual(GuestbookMessage.query.one().source_key,f'purchase:{self.purchase.id}')
        self.assertFalse(GuestbookMessage.query.one().approved)

    def test_verified_rejected_and_refunded_show_failure(self):
        for status in ('rejected','cancelled','refunded','charged_back'):
            response=self.callback(payment=self.payment(status=status))
            self.assertIn('Pagamento não concluído',response.get_data(as_text=True))
            self.assertNotIn('Pagamento aprovado',response.get_data(as_text=True))

    def test_provider_failure_is_pending_and_does_not_approve(self):
        with patch.object(MercadoPagoService,'fetch_payment',side_effect=RuntimeError('offline')):
            self.assertIn('Aguardando pagamento',self.client.get('/checkout/success?payment_id=123&status=approved').get_data(as_text=True))
        self.assertEqual(self.purchase.status,'pending')

    def test_legacy_false_approval_is_corrected_by_verified_pending(self):
        self.purchase.status='approved';db.session.commit()
        self.assertFalse(self.purchase.payment_verified)
        response=self.callback()
        self.assertNotIn('Pagamento aprovado',response.get_data(as_text=True))
        self.assertEqual(self.purchase.status,'pending')

    def test_approved_is_not_regressed_by_stale_pending_callback(self):
        self.webhook(self.payment(status='approved'))
        self.webhook(self.payment(status='pending'))
        self.assertEqual(self.purchase.status,'approved')
        self.assertEqual(GuestbookMessage.query.count(),1)

    def test_webhook_without_payment_cannot_approve_and_query_reference_is_ignored(self):
        response=self.client.post(f'/api/mercado-pago/webhook?external_reference={self.purchase.id}',json={'status':'approved'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.purchase.status,'pending')
        self.webhook(self.payment(status='approved'))
        self.assertEqual(self.purchase.status,'approved')

    def test_webhook_retries_provider_failure_and_ignores_merchant_order(self):
        with patch.object(MercadoPagoService,'fetch_payment',side_effect=RuntimeError('offline')):
            self.assertEqual(self.client.post('/api/mercado-pago/webhook',json={'type':'payment','data':{'id':123}}).status_code,503)
        with patch.object(MercadoPagoService,'fetch_payment') as fetch:
            self.client.post('/api/mercado-pago/webhook',json={'type':'merchant_order','data':{'id':123}})
            fetch.assert_not_called()
        self.assertEqual(self.purchase.status,'pending')

    def test_mismatched_amount_currency_reference_or_id_never_approves(self):
        for bad in ({'transaction_amount':1},{'transaction_amount':'NaN'},{'currency_id':'USD'},
                    {'external_reference':'999'},{'external_reference':'not-a-number'},{'id':999}):
            self.webhook(self.payment(status='approved',**bad))
            self.assertEqual(self.purchase.status,'pending',bad)
        self.assertEqual(GuestbookMessage.query.count(),0)

    def test_repeated_callbacks_do_not_duplicate_or_restore_deleted_message(self):
        for _ in range(3):self.webhook(self.payment(status='approved'))
        self.assertEqual(GuestbookMessage.query.count(),1)
        db.session.delete(GuestbookMessage.query.one());db.session.commit()
        self.webhook(self.payment(status='approved'))
        self.assertEqual(GuestbookMessage.query.count(),0)

    def test_rsvp_message_requires_valid_invitation_and_respects_moderation(self):
        data={'confirmation_code':'123456','attendance':'yes','guests_count':'2','message':'Recado do convite'}
        self.client.post('/rsvp',data=data)
        self.assertEqual(GuestbookMessage.query.count(),0)
        contact=ContactLead(name='Convidado',phone='11999991234',confirmation_code='123456')
        db.session.add(contact);db.session.commit()
        self.client.post('/rsvp',data=data)
        message=GuestbookMessage.query.one()
        self.assertEqual(message.source_key,f'rsvp:{RSVP.query.one().id}')
        self.assertFalse(message.approved)
        self.assertNotIn('Recado do convite',self.client.get('/mural').get_data(as_text=True))
        message.approved=True;db.session.commit()
        self.assertIn('Recado do convite',self.client.get('/mural').get_data(as_text=True))
        self.client.post('/rsvp',data=data)
        self.assertEqual(GuestbookMessage.query.count(),1)

    def test_auto_publish_setting_and_guestbook_disabled_are_respected(self):
        self.settings.require_guestbook_approval=False;db.session.commit()
        self.webhook(self.payment(status='approved'))
        self.assertTrue(GuestbookMessage.query.one().approved)
        self.settings.allow_guestbook=False
        self.purchase.guestbook_synced=False
        db.session.delete(GuestbookMessage.query.one());db.session.commit()
        self.webhook(self.payment(status='approved'))
        self.assertEqual(GuestbookMessage.query.count(),0)

    def test_existing_confirmed_messages_import_once_but_unverified_gifts_wait(self):
        db.session.add(RSVP(guest_name='Convidado',phone='11999991234',message='Recado antigo',confirmed_at=datetime.utcnow()))
        self.purchase.status='approved';db.session.commit()
        import_existing_messages();import_existing_messages()
        self.assertEqual(GuestbookMessage.query.count(),1)
        self.assertEqual(GuestbookMessage.query.one().message,'Recado antigo')
        self.webhook(self.payment(status='approved'))
        self.assertEqual(GuestbookMessage.query.count(),2)

    def test_public_wall_has_no_form_or_write_endpoint(self):
        html=self.client.get('/mural').get_data(as_text=True)
        self.assertNotIn('<form',html)
        self.assertNotIn('DEIXAR MEU RECADO',html)
        self.assertEqual(self.client.post('/mural',data={'author_name':'Fake','message':'Fake'}).status_code,405)

    def test_pix_preference_selects_pix_without_excluding_other_methods(self):
        response=Mock();response.json.return_value={'id':'pref-test','init_point':'https://www.mercadopago.com.br/checkout/test'}
        with patch('app.services.mercado_pago.requests.post',return_value=response) as post:
            result=MercadoPagoService.create_preference(self.purchase,'Jantar','https://site.test/success','https://site.test/pending','https://site.test/failure','https://site.test/webhook',payment_method='pix')
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['payment_methods']['default_payment_method_id'],'pix')
        self.assertEqual(payload['payment_methods']['excluded_payment_types'],[])
        self.assertEqual(payload['external_reference'],str(self.purchase.id))
        self.assertTrue(result['enabled'])

    def test_checkout_passes_pix_and_unpaid_message_does_not_enter_wall(self):
        with patch.object(MercadoPagoService,'create_preference',return_value={'enabled':True,'sandbox_url':'https://www.mercadopago.com.br/checkout/test','reference':'pref-test'}) as create:
            response=self.client.post(f'/presentes/{self.gift.id}/checkout',data={'buyer_name':'Maria','buyer_email':'maria@example.test','buyer_phone':'11999991234','message':'Outro recado','payment_method':'pix'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(create.call_args.kwargs['payment_method'],'pix')
        self.assertEqual(GuestbookMessage.query.count(),0)

    def test_invalid_payment_id_cannot_change_api_url_or_send_request(self):
        with patch('app.services.mercado_pago.requests.get') as get:
            for value in ('../search','123?access_token=bad','abc','1'*31):
                self.assertEqual(MercadoPagoService.fetch_payment(value),{})
            get.assert_not_called()

    def test_guestbook_and_payment_schema_migrate_without_approving_legacy_purchase(self):
        db.session.execute(text('DROP TABLE guestbook_message'))
        db.session.execute(text('CREATE TABLE guestbook_message (id INTEGER PRIMARY KEY,author_name VARCHAR(120),message TEXT,approved BOOLEAN,created_at TIMESTAMP,updated_at TIMESTAMP)'))
        db.session.execute(text('ALTER TABLE gift_purchase DROP COLUMN payment_verified'))
        db.session.execute(text('ALTER TABLE gift_purchase DROP COLUMN guestbook_synced'))
        db.session.execute(text('ALTER TABLE rsvp DROP COLUMN guestbook_synced'))
        db.session.commit();_sync_schema(self.app)
        self.assertIn('source_key',{c['name'] for c in inspect(db.engine).get_columns('guestbook_message')})
        self.assertIn('guestbook_synced',{c['name'] for c in inspect(db.engine).get_columns('rsvp')})
        db.session.expire_all()
        self.assertFalse(self.purchase.payment_verified)


if __name__=='__main__':unittest.main()
