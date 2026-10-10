import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
from app import create_app, db, _sync_schema
from app.models import (AdminUser, SiteSettings, Ceremony, FAQ, RSVP, GuestbookMessage, GiftItem,
                        ContactLead, WhatsAppCampaign, WhatsAppDispatch, CampaignJob, CampaignDelivery)
from app.services.site_content import seed_site_content
from app.services.campaign_queue import queue_campaign, process_next, queue_overview, queue_lock


class SiteUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='site-test-only', WA_INTERNAL_TOKEN='test-internal-secret')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        db.session.add(SiteSettings(wedding_time='18h30', wedding_location_name='Igreja cadastrada'))
        admin = AdminUser(name='Teste', email='test@example.test')
        admin.set_password('test-only-pass')
        db.session.add(admin)
        db.session.commit()
        seed_site_content()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['_user_id'] = admin.get_id()
            state['_fresh'] = True
            state['panel_csrf'] = 'test-token'
        self.now = datetime.utcnow()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def post(self, url, **data):
        return self.client.post(url, data={'csrf_token': 'test-token', **data})

    def campaign(self, message='Olá %contato%, código %codigo%', image=''):
        item = WhatsAppCampaign(title='Convite', message=message, image_path=image, target_tag='familia')
        db.session.add_all([item, ContactLead(name='Maria', phone='11999991234', tag='familia', confirmation_code='123456'),
                            ContactLead(name='Ana', phone='11999995678', tag='amigos', confirmation_code='234567')])
        db.session.commit()
        return item

    def send(self, now=None, **kwargs):
        with patch('app.services.campaign_queue.get_instance_status', return_value={'connected':True}), \
             patch('app.services.campaign_queue._post_send_text', return_value={'message_id':'text-id'}, **kwargs) as send_text, \
             patch('app.services.campaign_queue._post_send_image', return_value={'message_id':'image-id'}) as image:
            result = process_next(now or self.now)
        return result['state'], send_text.call_count, image.call_count

    def test_seed_preserves_settings_and_deleted_faq_stays_deleted(self):
        church = Ceremony.query.filter_by(kind='church').one()
        self.assertEqual((church.venue, church.event_time), ('Igreja cadastrada', '18:30'))
        self.assertEqual(Ceremony.query.count(), 2)
        self.assertEqual(FAQ.query.count(), 5)
        db.session.delete(FAQ.query.first())
        db.session.commit()
        seed_site_content()
        self.assertEqual(FAQ.query.count(), 4)
        self.assertEqual(Ceremony.query.count(), 2)

    def test_admin_ceremony_save_updates_home_and_campaign_fields(self):
        item = Ceremony.query.filter_by(kind='church').one()
        self.assertEqual(self.post('/admin/cerimonias', ceremony_id=item.id, title='Cerimônia', venue='Nova igreja',
                         address='Rua A', city='Cidade', event_date='2026-12-11', event_time='19:45', route_url='').status_code, 302)
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('19:45', html)
        self.assertIn('Nova igreja', html)
        self.assertEqual(SiteSettings.query.first().wedding_time, '19:45')
        self.assertNotEqual(Ceremony.query.filter_by(kind='party').one().maps_url, item.maps_url)
        self.post('/admin/cerimonias', ceremony_id=item.id, title='Bad', venue='Bad', event_time='25:00')
        self.assertEqual(item.event_time, '19:45')

    def test_faq_edit_order_visibility_and_delete(self):
        self.post('/admin/perguntas-frequentes', question='Pergunta nova', answer='Resposta nova', position=0, active='on')
        item = FAQ.query.filter_by(question='Pergunta nova').one()
        self.assertIn('Resposta nova', self.client.get('/').get_data(as_text=True))
        self.post('/admin/perguntas-frequentes', faq_id=item.id, question=item.question, answer='Oculta', position=1)
        self.assertNotIn('Oculta', self.client.get('/').get_data(as_text=True))
        self.post(f'/admin/perguntas-frequentes/{item.id}/excluir')
        seed_site_content()
        self.assertIsNone(db.session.get(FAQ, item.id))

    def test_rsvp_decline_ignores_count_and_yes_rejects_invalid_count(self):
        contact = ContactLead(name='Maria', phone='11999991234', confirmation_code='123456')
        db.session.add(contact)
        db.session.commit()
        self.client.post('/rsvp', data={'confirmation_code':'123456','attendance':'yes','guests_count':'abc'})
        self.assertEqual(RSVP.query.count(),0)
        self.client.post('/rsvp', data={'confirmation_code':'123456','attendance':'maybe','guests_count':'1'})
        self.assertEqual(RSVP.query.count(),0)
        self.client.post('/rsvp', data={'confirmation_code':'123456','attendance':'no','guests_count':'garbage'})
        self.assertEqual((RSVP.query.one().attendance,RSVP.query.one().guests_count),('no',0))

    def test_guestbook_only_publishes_approved_and_validates_limits(self):
        self.client.post('/mural', data={'author_name':'Maria','message':'Que sejam felizes'})
        self.assertEqual(GuestbookMessage.query.count(),1)
        self.assertNotIn('Que sejam felizes',self.client.get('/mural').get_data(as_text=True))
        self.client.post('/mural', data={'author_name':'x'*121,'message':'Recado'})
        self.assertEqual(GuestbookMessage.query.count(),1)

    def test_gift_decimal_price_and_invalid_values(self):
        self.post('/admin/presentes',title='Jantar',price='189.90',active='on',allow_multiple_purchases='on')
        item = GiftItem.query.one()
        self.assertEqual(item.price,189.90)
        self.post(f'/admin/presentes/{item.id}/editar',title='Jantar',price='1.234,56',active='on')
        self.assertEqual(item.price,1234.56)
        for price in ('nan','inf','-2','abc','0'):
            self.post('/admin/presentes',title='Inválido',price=price)
        self.assertEqual(GiftItem.query.count(),1)

    def test_new_mutations_require_csrf_and_internal_tick_requires_secret(self):
        for url in ('/admin/cerimonias','/admin/perguntas-frequentes','/admin/presentes','/admin/campanhas','/admin/campanhas/frequencia'):
            self.assertEqual(self.client.post(url,data={}).status_code,400)
        self.assertEqual(self.client.post('/api/whatsapp/campaigns/tick').status_code,403)
        self.assertEqual(self.client.post('/api/whatsapp/campaigns/tick',headers={'X-WA-Internal-Token':'test-internal-secret'}).json['state'],'idle')

    def test_queue_is_durable_filters_audience_and_deduplicates(self):
        item=self.campaign()
        with patch('app.services.campaign_queue._post_send_text') as send:
            self.assertEqual(queue_campaign(item,'https://site.test'),1)
            self.assertEqual(queue_campaign(item,'https://site.test'),0)
            send.assert_not_called()
        db.session.remove()
        self.assertEqual(CampaignJob.query.count(),1)
        self.assertIn('Maria',CampaignJob.query.one().message)
        self.assertIn('123456',CampaignJob.query.one().message)

    def test_global_interval_paces_separate_campaigns_and_success_does_not_repeat(self):
        item=self.campaign()
        queue_campaign(item,'https://site.test')
        another=WhatsAppCampaign(title='Outro',message='Texto',target_tag='todos')
        db.session.add(another);db.session.commit()
        queue_campaign(another,'https://site.test')
        self.assertEqual(self.send()[0],'sent')
        deadline=db.session.get(CampaignDelivery,1).next_send_at
        self.assertEqual(self.send(deadline-timedelta(milliseconds=1)),('waiting',0,0))
        self.assertEqual(self.send(deadline)[0],'sent')
        self.assertEqual(queue_campaign(item,'https://site.test'),0)

    def test_long_caption_is_two_paced_messages_and_retry_preserves_image(self):
        item=self.campaign(message='x'*1100,image='https://site.test/image.jpg')
        queue_campaign(item,'https://site.test')
        self.assertEqual(CampaignJob.query.count(),2)
        self.assertEqual(self.send(),('sent',0,1))
        deadline=db.session.get(CampaignDelivery,1).next_send_at
        self.assertEqual(self.send(deadline-timedelta(seconds=1)),('waiting',0,0))
        self.assertEqual(self.send(deadline,side_effect=RuntimeError('Connection lost'))[0],'error')
        self.assertTrue(item.queue_paused)
        self.assertEqual(CampaignJob.query.filter_by(kind='image').one().status,'sent')
        ContactLead.query.filter_by(tag='familia').one().tag='outro'
        db.session.commit()
        self.assertEqual(queue_campaign(item,'https://site.test','errors'),1)
        self.assertEqual(CampaignJob.query.count(),2)
        self.assertEqual(self.send(db.session.get(CampaignDelivery,1).next_send_at),('sent',1,0))
        self.assertEqual(WhatsAppDispatch.query.one().status,'sent')

    def test_disconnect_and_pause_do_not_consume_queue(self):
        item=self.campaign();queue_campaign(item,'https://site.test')
        with patch('app.services.campaign_queue.get_instance_status',return_value={'connected':False}):
            self.assertEqual(process_next(self.now)['state'],'disconnected')
        self.assertEqual(CampaignJob.query.one().status,'queued')
        item.queue_paused=True;db.session.commit()
        self.assertEqual(self.send(),('idle',0,0))
        self.assertEqual(queue_overview()[item.id]['remaining'],1)

    def test_error_pauses_campaign_and_adding_contacts_does_not_unpause(self):
        item=self.campaign();queue_campaign(item,'https://site.test')
        self.assertEqual(self.send(side_effect=RuntimeError('error'))[0],'error')
        db.session.add(ContactLead(name='Novo',phone='11999990000',tag='familia'));db.session.commit()
        queue_campaign(item,'https://site.test')
        self.assertTrue(item.queue_paused)
        self.assertEqual(self.send(self.now+timedelta(minutes=1)),('idle',0,0))

    def test_crash_recovery_requires_review_and_does_not_repeat_uncertain_send(self):
        item=self.campaign();queue_campaign(item,'https://site.test')
        job=CampaignJob.query.one();job.status='sending';job.started_at=self.now-timedelta(minutes=3)
        db.session.commit()
        self.assertEqual(self.send(),('idle',0,0))
        self.assertEqual(job.status,'uncertain')
        self.assertTrue(item.queue_paused)
        self.assertIn('pode ter sido entregue',job.error)

    def test_concurrent_tick_is_rejected(self):
        self.campaign()
        with queue_lock():
            self.assertEqual(process_next()['state'],'busy')

    def test_frequency_limits_csrf_and_future_deadline(self):
        for seconds in ('1','14','601','invalid'):
            self.post('/admin/campanhas/frequencia',interval_seconds=seconds)
            self.assertEqual(db.session.get(CampaignDelivery,1).interval_seconds,15)
        self.post('/admin/campanhas/frequencia',interval_seconds=30)
        pacing=db.session.get(CampaignDelivery,1)
        self.assertEqual(pacing.interval_seconds,30)
        self.assertGreater(pacing.next_send_at,self.now+timedelta(seconds=29))

    def test_campaign_deletion_cascades_jobs_and_enqueues_without_network(self):
        item=self.campaign()
        with patch('app.services.campaign_queue._post_send_text') as send:
            self.post(f'/admin/campanhas/{item.id}/disparar',send_scope='unsent')
            send.assert_not_called()
        self.assertEqual(CampaignJob.query.count(),1)
        self.post(f'/admin/campanhas/{item.id}/excluir')
        self.assertEqual(CampaignJob.query.count(),0)
        self.assertEqual(WhatsAppDispatch.query.count(),0)

    def test_legacy_campaign_schema_migrates(self):
        # Recreate only the legacy table, then run the additive migration.
        from sqlalchemy import text, inspect
        db.session.execute(text('DROP TABLE whatsapp_campaign'))
        db.session.execute(text('CREATE TABLE whatsapp_campaign (id INTEGER PRIMARY KEY, title VARCHAR(180), message TEXT, active BOOLEAN, target_tag VARCHAR(80), image_path VARCHAR(255), created_at TIMESTAMP, updated_at TIMESTAMP)'))
        db.session.execute(text("INSERT INTO whatsapp_campaign (id,title,message) VALUES (5,'Old','Text')"));db.session.commit()
        _sync_schema(self.app)
        columns={c['name'] for c in inspect(db.engine).get_columns('whatsapp_campaign')}
        self.assertIn('queue_paused',columns)
        self.assertFalse(db.session.get(WhatsAppCampaign,5).queue_paused)


if __name__ == '__main__':
    unittest.main()
