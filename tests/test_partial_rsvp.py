import unittest
from datetime import datetime
from werkzeug.datastructures import MultiDict
import test_smart_rsvp as baseline
from app import db, _sync_schema
from app.models import RSVP, ContactLead
from app.services.contact_import import import_overview
from app.services.invitations import invitation_report


class PartialRSVPTests(unittest.TestCase):
    setUpClass = classmethod(baseline.SmartRSVPTests.setUpClass.__func__)
    setUp = baseline.SmartRSVPTests.setUp
    tearDown = baseline.SmartRSVPTests.tearDown
    contact = baseline.SmartRSVPTests.contact
    open = baseline.SmartRSVPTests.open
    reply = baseline.SmartRSVPTests.reply
    def selected_reply(self, positions, attendance='yes', **extra):
        with self.client.session_transaction() as state:
            token = state['rsvp_csrf']
        fields = MultiDict({'action': 'reply', 'csrf_token': token, 'selection_present': '1',
                            'attendance': attendance, **extra})
        for position in positions:
            fields.add('attendee', str(position))
        return self.client.post('/rsvp', data=fields, follow_redirects=True)

    def test_only_husband_attends_and_two_people_are_absent(self):
        self.contact('Pedro & Maria & BB'); self.open()
        html = self.selected_reply([0], guest_name='Outra pessoa', guests_count='99').get_data(as_text=True)
        response = RSVP.query.one()
        self.assertEqual((response.guests_count, response.selected_names), (1, ['Pedro']))
        self.assertEqual(response.guest_name, 'Pedro & Maria & BB')
        self.assertIn('1 pessoa confirmada', html)
        self.assertIn('Quem vai: <strong>Pedro</strong>', html)
        self.assertIn('data-gift-transition', html)
        totals = invitation_report()[2]
        self.assertEqual((totals['yes'], totals['no'], totals['people']), (1, 2, 3))

    def test_wife_and_child_attend(self):
        self.contact('Pedro & Maria & BB'); self.open()
        self.selected_reply([1, 2])
        self.assertEqual(RSVP.query.one().selected_names, ['Maria', 'BB'])
        self.assertEqual(RSVP.query.one().guests_count, 2)
        self.assertEqual((invitation_report()[2]['yes'], invitation_report()[2]['no']), (2, 1))

    def test_cannot_add_guest_repeat_member_or_accept_empty_selection(self):
        self.contact(); self.open()
        for positions in ([], ['3'], ['-1'], ['name'], ['0', '0'], ['0', '1', '2', '3'], ['1' * 10000]):
            self.selected_reply(positions)
            self.assertEqual(RSVP.query.count(), 0)
        self.selected_reply([0, 1, 2])
        self.assertEqual(RSVP.query.one().guests_count, 3)

    def test_decline_ignores_selection_and_does_not_animate(self):
        self.contact(); self.open()
        html = self.selected_reply(['999'], attendance='no').get_data(as_text=True)
        self.assertEqual((RSVP.query.one().guests_count, RSVP.query.one().selected_names), (0, []))
        self.assertNotIn('data-gift-transition', html)
        self.assertNotIn('data-gift-handoff', html)
        self.assertEqual(invitation_report()[2]['no'], 3)

    def test_reopening_or_repeating_partial_reply_preserves_selection_without_animation(self):
        self.contact(); self.open(); self.selected_reply([1, 2])
        original = RSVP.query.one().confirmed_at
        for _ in range(2):
            html = self.selected_reply([0, 1, 2]).get_data(as_text=True)
            self.assertNotIn('data-gift-transition', html)
        html = self.open().get_data(as_text=True)
        self.assertNotIn('data-gift-transition', html)
        self.assertEqual(RSVP.query.one().selected_names, ['Anita', 'BB'])
        self.assertEqual(RSVP.query.one().confirmed_at, original)
        self.assertEqual(RSVP.query.count(), 1)

    def test_contacts_preview_counts_all_invitations_and_updates_when_name_changes(self):
        self.contact('  Kevin & & Anita &  BB & ', '111111')
        second = self.contact('Maria e João', '222222')
        self.assertEqual((import_overview()['total'], import_overview()['people']), (2, 4))
        second.name = 'Maria & João & Pedro'; db.session.commit()
        self.assertEqual(import_overview()['people'], 6)

    def test_existing_responses_without_selection_are_not_rewritten(self):
        contact = self.contact()
        record = RSVP(contact_id=contact.id, guest_name=contact.name, phone=contact.phone,
                      attendance='yes', guests_count=1, confirmed_at=datetime.utcnow())
        db.session.add(record); db.session.commit()
        self.open()
        self.assertEqual(invitation_report()[2]['yes'], 3)
        self.assertEqual((record.guests_count, record.attendee_names), (1, ''))

    def test_additive_migration_preserves_old_response_columns(self):
        from sqlalchemy import text, inspect
        contact = self.contact()
        db.session.add(RSVP(contact_id=contact.id, guest_name=contact.name, phone=contact.phone,
                            attendance='no', guests_count=0, confirmed_at=datetime.utcnow()))
        db.session.commit()
        db.session.execute(text('ALTER TABLE rsvp DROP COLUMN attendee_names')); db.session.commit()
        _sync_schema(self.app)
        self.assertIn('attendee_names', {column['name'] for column in inspect(db.engine).get_columns('rsvp')})
        db.session.expire_all()
        self.assertEqual((RSVP.query.one().attendance, RSVP.query.one().guests_count), ('no', 0))
