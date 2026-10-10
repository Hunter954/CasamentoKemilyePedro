import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)
from werkzeug.security import generate_password_hash
from app import create_app, db
from app.models import AdminUser


class AdminUserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='users-test-only')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.owner = self.add_user('Owner', 'owner@example.test', 'admin')
        self.admin = self.app.test_client()
        self.sign_in(self.admin, self.owner.email)
        self.request(self.admin, 'get', '/admin/usuarios')

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def add_user(self, name, email, role='manager', enabled=True):
        user = AdminUser(name=name, email=email, role=role, enabled=enabled)
        user.set_password('initial-pass')
        db.session.add(user)
        db.session.commit()
        return user

    def request(self, client, method, url, **kwargs):
        # Each browser request must get its own Flask current_user cache.
        with self.app.app_context():
            response = getattr(client, method)(url, **kwargs)
        db.session.expire_all()
        return response

    def sign_in(self, client, email, password='initial-pass'):
        return self.request(client, 'post', '/admin/login', data={'email': email, 'password': password})

    def token(self):
        with self.admin.session_transaction() as state:
            return state['users_csrf']

    def form(self, **overrides):
        values = {'csrf_token': self.token(), 'name': 'Novo usuário', 'email': 'new@example.test',
                  'role': 'manager', 'enabled': 'on', 'password': 'new-user-pass', 'password_confirmation': 'new-user-pass'}
        values.update(overrides)
        return values

    def save(self, **overrides):
        return self.request(self.admin, 'post', '/admin/usuarios', data=self.form(**overrides))

    def test_create_hashes_password_normalizes_email_and_can_log_in(self):
        self.assertEqual(self.save(email=' NEW@EXAMPLE.TEST ').status_code, 302)
        user = AdminUser.query.filter_by(email='new@example.test').one()
        self.assertEqual((user.role, user.enabled), ('manager', True))
        self.assertNotEqual(user.password_hash, 'new-user-pass')
        self.assertTrue(user.check_password('new-user-pass'))
        client = self.app.test_client()
        self.assertEqual(self.sign_in(client, user.email, 'new-user-pass').status_code, 302)
        self.assertEqual(self.request(client, 'get', '/admin/').status_code, 200)

    def test_anonymous_and_manager_cannot_manage_accounts_or_escalate(self):
        manager = self.add_user('Manager', 'manager@example.test')
        client = self.app.test_client()
        self.assertEqual(self.request(client, 'get', '/admin/usuarios').status_code, 302)
        self.sign_in(client, manager.email)
        for url in ('/admin/usuarios', f'/admin/usuarios/{self.owner.id}/acesso', f'/admin/usuarios/{self.owner.id}/excluir'):
            self.assertEqual(self.request(client, 'post', url, data=self.form(role='admin')).status_code, 403)
        self.assertEqual(self.request(client, 'get', '/admin/usuarios').status_code, 403)
        dashboard = self.request(client, 'get', '/admin/').data.decode()
        self.assertNotIn('href="/admin/usuarios"', dashboard)
        self.assertIn('href="/admin/contatos"', dashboard)

    def test_csrf_required_for_all_mutations(self):
        for url in ('/admin/usuarios', f'/admin/usuarios/{self.owner.id}/acesso', f'/admin/usuarios/{self.owner.id}/excluir'):
            self.assertEqual(self.request(self.admin, 'post', url, data={}).status_code, 400)
        self.assertEqual(AdminUser.query.count(), 1)

    def test_duplicate_case_insensitive_email_and_invalid_fields(self):
        response = self.save(email='OWNER@EXAMPLE.TEST')
        self.assertEqual(response.status_code, 422)
        self.assertIn('já está cadastrado', response.data.decode())
        for override in ({'name': ''}, {'email': 'invalid'}, {'role': 'superuser'}, {'password': 'short'},
                         {'password_confirmation': 'different'}, {'password': ' ' * 8, 'password_confirmation': ' ' * 8}):
            self.assertEqual(self.save(**override).status_code, 422)
        self.assertEqual(AdminUser.query.count(), 1)
        self.assertNotIn(b'new-user-pass', response.data)

    def test_edit_keeps_password_when_empty_and_can_change_profile(self):
        user = self.add_user('Old name', 'old@example.test')
        old_hash = user.password_hash
        response = self.save(user_id=user.id, name='New name', email='updated@example.test', role='admin',
                             password='', password_confirmation='')
        self.assertEqual(response.status_code, 302)
        self.assertEqual((user.name, user.email, user.role), ('New name', 'updated@example.test', 'admin'))
        self.assertEqual(user.password_hash, old_hash)

    def test_password_reset_invalidates_old_session_and_requires_new_password(self):
        user = self.add_user('Manager', 'manager@example.test')
        client = self.app.test_client()
        self.sign_in(client, user.email)
        response = self.save(user_id=user.id, name=user.name, email=user.email)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.request(client, 'get', '/admin/').status_code, 302)
        self.assertEqual(self.sign_in(client, user.email).status_code, 200)
        self.assertEqual(self.sign_in(client, user.email, 'new-user-pass').status_code, 302)

    def test_deactivation_revokes_session_blocks_login_and_reactivation_works(self):
        user = self.add_user('Manager', 'manager@example.test')
        client = self.app.test_client()
        self.sign_in(client, user.email)
        url = f'/admin/usuarios/{user.id}/acesso'
        self.request(self.admin, 'post', url, data={'csrf_token': self.token()})
        self.assertFalse(user.enabled)
        self.assertEqual(self.request(client, 'get', '/admin/').status_code, 302)
        self.assertEqual(self.sign_in(client, user.email).status_code, 200)
        self.request(self.admin, 'post', url, data={'csrf_token': self.token()})
        self.assertTrue(user.enabled)
        self.assertEqual(self.sign_in(client, user.email).status_code, 302)

    def test_delete_removes_account_and_revokes_session(self):
        user = self.add_user('Manager', 'manager@example.test')
        user_id = user.id
        client = self.app.test_client()
        self.sign_in(client, user.email)
        self.request(self.admin, 'post', f'/admin/usuarios/{user_id}/excluir', data={'csrf_token': self.token()})
        self.assertIsNone(db.session.get(AdminUser, user_id))
        self.assertEqual(self.request(client, 'get', '/admin/').status_code, 302)

    def test_last_admin_cannot_be_demoted_and_self_cannot_be_disabled_deleted(self):
        response = self.save(user_id=self.owner.id, name=self.owner.name, email=self.owner.email, role='manager',
                             password='', password_confirmation='')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.owner.role, 'admin')
        for action in ('acesso', 'excluir'):
            self.request(self.admin, 'post', f'/admin/usuarios/{self.owner.id}/{action}', data={'csrf_token': self.token()})
        self.assertTrue(self.owner.enabled)
        self.assertIsNotNone(db.session.get(AdminUser, self.owner.id))

    def test_own_password_edit_preserves_current_session_but_revokes_other_sessions(self):
        other = self.app.test_client()
        self.sign_in(other, self.owner.email)
        self.assertEqual(self.save(user_id=self.owner.id, name=self.owner.name, email=self.owner.email, role='admin').status_code, 302)
        self.assertEqual(self.request(self.admin, 'get', '/admin/usuarios').status_code, 200)
        self.assertEqual(self.request(other, 'get', '/admin/').status_code, 302)

    def test_primary_account_edit_locks_credentials_and_preserves_other_users(self):
        self.owner.is_primary = True
        db.session.commit()
        self.add_user('Assistant', 'assistant@example.test')
        self.assertEqual(self.save(user_id=self.owner.id, name='Principal', email=self.owner.email, role='admin',
                             password='', password_confirmation='').status_code, 302)
        for override in ({'email': 'changed@example.test'}, {'role': 'manager'}, {'enabled': ''},
                         {'password': 'new-user-pass', 'password_confirmation': 'new-user-pass'}):
            data = {'user_id': self.owner.id, 'name': self.owner.name, 'email': self.owner.email,
                    'role': 'admin', 'password': '', 'password_confirmation': '', **override}
            self.assertEqual(self.save(**data).status_code, 422)
        self.assertEqual(AdminUser.query.count(), 2)
        self.assertTrue(self.owner.check_password('initial-pass'))

    def test_search_filter_and_error_values_are_preserved(self):
        self.add_user('Inactive manager', 'inactive@example.test', enabled=False)
        self.assertIn(b'inactive@example.test', self.request(self.admin, 'get', '/admin/usuarios?status=inactive').data)
        self.assertNotIn(b'owner@example.test</small>', self.request(self.admin, 'get', '/admin/usuarios?status=inactive').data)
        self.assertIn(b'inactive@example.test', self.request(self.admin, 'get', '/admin/usuarios?q=inactive').data)
        response = self.save(name='Preserved name', email='bad')
        self.assertIn(b'Preserved name', response.data)
        self.assertIn(b'value="bad"', response.data)
        self.assertNotIn(b'value="new-user-pass"', response.data)

    def test_legacy_signed_sessions_work_until_credentials_change(self):
        legacy = self.app.test_client()
        with legacy.session_transaction() as state:
            state['_user_id'] = str(self.owner.id)
            state['_fresh'] = True
        self.assertEqual(self.request(legacy, 'get', '/admin/usuarios').status_code, 200)
        self.owner.set_password('changed-pass')
        db.session.commit()
        self.assertEqual(self.request(legacy, 'get', '/admin/usuarios').status_code, 302)

    def test_legacy_schema_migrates_without_changing_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.db'
            password_hash = generate_password_hash('legacy-pass')
            with sqlite3.connect(path) as connection:
                connection.execute('CREATE TABLE admin_user (id INTEGER PRIMARY KEY, name VARCHAR(120), email VARCHAR(120) UNIQUE, password_hash VARCHAR(255), created_at DATETIME, updated_at DATETIME)')
                connection.execute('INSERT INTO admin_user(id,name,email,password_hash) VALUES(1,?,?,?)', ('Legacy', 'legacy@example.test', password_hash))
            connection.close()
            with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///' + path.as_posix()}):
                app = create_app()
                with app.app_context():
                    user = db.session.get(AdminUser, 1)
                    self.assertEqual((user.role, user.enabled, user.session_version, user.password_hash), ('admin', True, 1, password_hash))
                    db.session.remove()
                    db.engine.dispose()

    def test_restarts_preserve_added_accounts_and_only_sync_primary_account(self):
        with tempfile.TemporaryDirectory() as folder:
            url = 'sqlite:///' + (Path(folder) / 'restart.db').as_posix()
            with patch.dict(os.environ, {'DATABASE_URL': url, 'ADMIN_EMAIL': 'primary@example.test', 'ADMIN_PASSWORD': 'bootstrap-pass'}):
                app = create_app()
                with app.app_context():
                    primary = AdminUser.query.filter_by(is_primary=True).one()
                    extra = AdminUser(name='Extra', email='extra@example.test', role='manager', enabled=False)
                    extra.set_password('extra-pass')
                    db.session.add(extra)
                    db.session.commit()
                    primary_id = primary.id
                    db.session.remove()
                    db.engine.dispose()
                app = create_app()
                with app.app_context():
                    self.assertEqual(AdminUser.query.count(), 2)
                    self.assertEqual(AdminUser.query.filter_by(is_primary=True).one().id, primary_id)
                    extra = AdminUser.query.filter_by(email='extra@example.test').one()
                    self.assertEqual((extra.role, extra.enabled), ('manager', False))
                    self.assertTrue(extra.check_password('extra-pass'))
                    db.session.remove()
                    db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
