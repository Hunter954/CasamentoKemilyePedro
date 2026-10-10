"""Administrative account management; access is restricted to administrators."""
import hmac
import re
import secrets
import threading
from contextlib import contextmanager
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AdminUser

users_bp = Blueprint('admin_users', __name__)
_users_lock = threading.RLock()
ROLES = {'admin': 'Administrador', 'manager': 'Gerente'}


def admin_only(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.can_manage_users:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def check_csrf():
    expected = session.get('users_csrf', '')
    received = request.form.get('csrf_token', '')
    if not expected or not hmac.compare_digest(expected.encode(), received.encode()):
        abort(400, description='Atualize a página e tente novamente.')


@contextmanager
def user_write_lock():
    with _users_lock:
        try:
            if db.engine.dialect.name == 'postgresql':
                db.session.execute(text('SELECT pg_advisory_xact_lock(74201952)'))
            actor = db.session.get(AdminUser, current_user.id, populate_existing=True)
            claimed_id = str(session.get('_user_id') or '').split(':', 1)
            claimed_version = int(claimed_id[1]) if len(claimed_id) == 2 else 1
            if not actor or not actor.can_manage_users or actor.session_version != claimed_version:
                abort(403)
            yield
        except Exception:
            db.session.rollback()
            raise


def access_error(user, role, enabled, deleting=False):
    if user.is_primary:
        return 'A conta principal deve continuar ativa como administrador.'
    if user.id == current_user.id and (deleting or not enabled):
        return 'Você não pode excluir ou desativar a conta que está usando.'
    if user.enabled and user.role == 'admin' and (deleting or not enabled or role != 'admin'):
        others = AdminUser.query.filter(AdminUser.id != user.id, AdminUser.enabled.is_(True), AdminUser.role == 'admin').count()
        if not others:
            return 'Mantenha pelo menos um administrador ativo para gerenciar os acessos.'
    return ''


def render_users(editing=None, values=None, errors=None, status=200):
    token = session.setdefault('users_csrf', secrets.token_urlsafe(32))
    if values is None:
        values = {'name': editing.name if editing else '', 'email': editing.email if editing else '',
                  'role': editing.role if editing else 'manager', 'enabled': editing.enabled if editing else True}
    search = request.args.get('q', '').strip()[:120]
    state = request.args.get('status', '')
    query = AdminUser.query
    if search:
        query = query.filter(db.or_(db.func.lower(AdminUser.name).contains(search.lower(), autoescape=True),
                                   db.func.lower(AdminUser.email).contains(search.lower(), autoescape=True)))
    if state in ('active', 'inactive'):
        query = query.filter(AdminUser.enabled.is_(state == 'active'))
    pagination = query.order_by(AdminUser.is_primary.desc(), AdminUser.created_at.desc(), AdminUser.id.desc()).paginate(
        page=max(1, request.args.get('page', 1, type=int)), per_page=20, error_out=False)
    return render_template('admin/users.html', editing_user=editing, values=values, errors=errors or {},
                           csrf_token=token, roles=ROLES, users=pagination.items, pagination=pagination,
                           search=search, state=state, total=AdminUser.query.count(),
                           active=AdminUser.query.filter_by(enabled=True).count()), status


@users_bp.route('', methods=['GET', 'POST'])
@admin_only
def index():
    if request.method == 'GET':
        edit_id = request.args.get('edit', type=int)
        editing = db.get_or_404(AdminUser, edit_id) if edit_id else None
        return render_users(editing)
    check_csrf()
    user_id = request.form.get('user_id', type=int)
    editing = db.get_or_404(AdminUser, user_id) if user_id else None
    values = {'name': request.form.get('name', '').strip(), 'email': request.form.get('email', '').strip().lower(),
              'role': request.form.get('role', 'manager'), 'enabled': request.form.get('enabled') == 'on'}
    password = request.form.get('password', '')
    confirmation = request.form.get('password_confirmation', '')
    errors = {}
    if not values['name'] or len(values['name']) > 120:
        errors['name'] = 'Informe um nome com até 120 caracteres.'
    if len(values['email']) > 120 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
        errors['email'] = 'Informe um e-mail válido.'
    if values['role'] not in ROLES:
        errors['role'] = 'Escolha um dos perfis disponíveis.'
    if not editing or password or confirmation:
        if not 8 <= len(password) <= 128 or password.isspace():
            errors['password'] = 'Use uma senha de 8 a 128 caracteres.'
        if password != confirmation:
            errors['password_confirmation'] = 'As senhas precisam ser iguais.'
    if errors:
        return render_users(editing, values, errors, 422)
    try:
        with user_write_lock():
            if editing:
                db.session.refresh(editing)
                if editing.is_primary:
                    if (values['email'] != editing.email or values['role'] != 'admin' or not values['enabled'] or password):
                        errors['access'] = 'O e-mail, a senha e o acesso da conta principal são gerenciados pela configuração do site.'
                else:
                    reason = access_error(editing, values['role'], values['enabled']) if editing.role != values['role'] or editing.enabled != values['enabled'] else ''
                    if reason:
                        errors['access'] = reason
            duplicate = AdminUser.query.filter(db.func.lower(AdminUser.email) == values['email'])
            if editing:
                duplicate = duplicate.filter(AdminUser.id != editing.id)
            if duplicate.first():
                errors['email'] = 'Este e-mail já está cadastrado. Use outro ou edite a conta existente.'
            if errors:
                db.session.rollback()
                return render_users(editing, values, errors, 422)
            user = editing or AdminUser()
            sensitive_change = editing and (user.email != values['email'] or user.role != values['role'] or user.enabled != values['enabled'])
            previous_version = user.session_version or 1
            user.name, user.email = values['name'], values['email']
            user.role, user.enabled = values['role'], values['enabled']
            if password:
                user.set_password(password)
            if sensitive_change:
                user.session_version = previous_version + 1
            db.session.add(user)
            db.session.commit()
            if editing and user.id == current_user.id:
                login_user(user)
                if not user.can_manage_users:
                    flash('Sua conta foi atualizada. Agora você tem o perfil Gerente.', 'success')
                    return redirect(url_for('admin.dashboard'))
        flash('Usuário atualizado.' if editing else 'Usuário criado. Ele já pode entrar com o e-mail e a senha cadastrados.' if user.enabled else 'Usuário criado com acesso desativado.', 'success')
        return redirect(url_for('admin_users.index'))
    except IntegrityError:
        db.session.rollback()
        return render_users(editing, values, {'email': 'Este e-mail já está cadastrado.'}, 422)


@users_bp.route('/<int:user_id>/acesso', methods=['POST'])
@admin_only
def toggle_access(user_id):
    check_csrf()
    with user_write_lock():
        user = db.get_or_404(AdminUser, user_id)
        reason = access_error(user, user.role, not user.enabled)
        if reason:
            flash(reason, 'warning')
        else:
            user.enabled = not user.enabled
            user.session_version += 1
            flash(f'Acesso de {user.name} ' + ('ativado.' if user.enabled else 'desativado.'), 'success')
        db.session.commit()
    return redirect(url_for('admin_users.index'))


@users_bp.route('/<int:user_id>/excluir', methods=['POST'])
@admin_only
def delete(user_id):
    check_csrf()
    with user_write_lock():
        user = db.get_or_404(AdminUser, user_id)
        reason = access_error(user, user.role, False, deleting=True)
        if reason:
            flash(reason, 'warning')
        else:
            db.session.delete(user)
            flash('Usuário excluído. Seu acesso ao painel foi encerrado.', 'success')
        db.session.commit()
    return redirect(url_for('admin_users.index'))
