import os
from flask import Flask, send_from_directory, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import inspect, text
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from .utils import format_currency, format_phone

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def _sync_schema(app):
    inspector = inspect(db.engine)

    if inspector.has_table('admin_user'):
        user_columns = {column['name'] for column in inspector.get_columns('admin_user')}
        for name, definition in {
            'role': "VARCHAR(20) NOT NULL DEFAULT 'admin'",
            'enabled': 'BOOLEAN NOT NULL DEFAULT TRUE',
            'session_version': 'INTEGER NOT NULL DEFAULT 1',
            'is_primary': 'BOOLEAN NOT NULL DEFAULT FALSE',
        }.items():
            if name not in user_columns:
                db.session.execute(text(f'ALTER TABLE admin_user ADD COLUMN {name} {definition}'))
        db.session.commit()

    if inspector.has_table('gift_item'):
        gift_columns = {column['name'] for column in inspector.get_columns('gift_item')}
        if 'allow_multiple_purchases' not in gift_columns:
            db.session.execute(text("ALTER TABLE gift_item ADD COLUMN allow_multiple_purchases BOOLEAN DEFAULT TRUE"))
            db.session.commit()

    if inspector.has_table('site_settings'):
        settings_columns = {column['name'] for column in inspector.get_columns('site_settings')}
        if 'mercado_pago_enabled' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN mercado_pago_enabled BOOLEAN DEFAULT FALSE"))
        if 'mercado_pago_access_token' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN mercado_pago_access_token TEXT DEFAULT ''"))
        if 'mercado_pago_public_key' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN mercado_pago_public_key VARCHAR(255) DEFAULT ''"))
        if 'zapi_enabled' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_enabled BOOLEAN DEFAULT FALSE"))
        if 'zapi_instance_id' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_instance_id VARCHAR(120) DEFAULT ''"))
        if 'zapi_token' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_token VARCHAR(255) DEFAULT ''"))
        if 'zapi_client_token' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_client_token VARCHAR(255) DEFAULT ''"))
        if 'zapi_sender_number' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_sender_number VARCHAR(40) DEFAULT ''"))
        if 'zapi_base_url' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_base_url VARCHAR(255) DEFAULT 'https://api.z-api.io'"))
        if 'zapi_delay_seconds' not in settings_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN zapi_delay_seconds INTEGER DEFAULT 4"))
        db.session.commit()

    if inspector.has_table('contact_lead'):
        contact_columns = {column['name'] for column in inspector.get_columns('contact_lead')}
        if 'confirmation_code' not in contact_columns:
            db.session.execute(text("ALTER TABLE contact_lead ADD COLUMN confirmation_code VARCHAR(20) DEFAULT ''"))
        db.session.commit()

    if inspector.has_table('rsvp'):
        rsvp_columns = {column['name'] for column in inspector.get_columns('rsvp')}
        if 'contact_id' not in rsvp_columns:
            db.session.execute(text("ALTER TABLE rsvp ADD COLUMN contact_id INTEGER"))
        if 'confirmation_code' not in rsvp_columns:
            db.session.execute(text("ALTER TABLE rsvp ADD COLUMN confirmation_code VARCHAR(20) DEFAULT ''"))
        if 'confirmed_at' not in rsvp_columns:
            db.session.execute(text("ALTER TABLE rsvp ADD COLUMN confirmed_at TIMESTAMP"))
        db.session.commit()

    if inspector.has_table('whatsapp_campaign'):
        campaign_columns = {column['name'] for column in inspector.get_columns('whatsapp_campaign')}
        if 'target_tag' not in campaign_columns:
            db.session.execute(text("ALTER TABLE whatsapp_campaign ADD COLUMN target_tag VARCHAR(80) DEFAULT 'todos'"))
        if 'image_path' not in campaign_columns:
            db.session.execute(text("ALTER TABLE whatsapp_campaign ADD COLUMN image_path VARCHAR(255) DEFAULT ''"))
        db.session.commit()

    if inspector.has_table('whatsapp_dispatch'):
        dispatch_columns = {column['name'] for column in inspector.get_columns('whatsapp_dispatch')}
        if 'phone_sent' not in dispatch_columns:
            db.session.execute(text("ALTER TABLE whatsapp_dispatch ADD COLUMN phone_sent VARCHAR(40) DEFAULT ''"))
        if 'provider_message_id' not in dispatch_columns:
            db.session.execute(text("ALTER TABLE whatsapp_dispatch ADD COLUMN provider_message_id VARCHAR(120) DEFAULT ''"))
        if 'response_body' not in dispatch_columns:
            db.session.execute(text("ALTER TABLE whatsapp_dispatch ADD COLUMN response_body TEXT DEFAULT ''"))
        if 'error_message' not in dispatch_columns:
            db.session.execute(text("ALTER TABLE whatsapp_dispatch ADD COLUMN error_message TEXT DEFAULT ''"))
        db.session.commit()

    if inspector.has_table('whatsapp_webhook_log'):
        webhook_columns = {column['name'] for column in inspector.get_columns('whatsapp_webhook_log')}
        if 'external_message_id' not in webhook_columns:
            db.session.execute(text("ALTER TABLE whatsapp_webhook_log ADD COLUMN external_message_id VARCHAR(120) DEFAULT ''"))
        if 'phone' not in webhook_columns:
            db.session.execute(text("ALTER TABLE whatsapp_webhook_log ADD COLUMN phone VARCHAR(40) DEFAULT ''"))
        if 'notes' not in webhook_columns:
            db.session.execute(text("ALTER TABLE whatsapp_webhook_log ADD COLUMN notes TEXT DEFAULT ''"))
        db.session.commit()

    # Migração segura dos nomes usados nas versões/modelos anteriores do projeto.
    if inspector.has_table('site_settings'):
        db.session.execute(text("UPDATE site_settings SET couple_names='Kemily & Pedro' WHERE couple_names IN ('Ana & João', 'Darlon & Julia')"))
        db.session.commit()

    from .services.whatsapp import ensure_all_contact_codes
    ensure_all_contact_codes(commit=True)


def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
    database_url = os.getenv('DATABASE_URL', 'sqlite:///wedding.db')
    # Railway pode fornecer postgres://, postgresql:// ou postgresql+psycopg://.
    # O projeto usa psycopg2-binary, então normalizamos explicitamente o driver.
    if database_url.startswith('postgres://'):
        database_url = 'postgresql+psycopg2://' + database_url[len('postgres://'):]
    elif database_url.startswith('postgresql+psycopg://'):
        database_url = 'postgresql+psycopg2://' + database_url[len('postgresql+psycopg://'):]
    elif database_url.startswith('postgresql://'):
        database_url = 'postgresql+psycopg2://' + database_url[len('postgresql://'):]
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_DIR'] = os.getenv('UPLOAD_DIR', os.path.join(app.root_path, 'static', 'uploads'))
    app.config['ADMIN_EMAIL'] = os.getenv('ADMIN_EMAIL', 'admin@casamento.com')
    app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', '123456')
    app.config['MERCADO_PAGO_ACCESS_TOKEN'] = os.getenv('MERCADO_PAGO_ACCESS_TOKEN', '')
    app.config['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY', '')
    app.config['WHATSAPP_SENDER_NUMBER'] = os.getenv('WHATSAPP_SENDER_NUMBER', '')
    app.config['ZAPI_ENABLED'] = os.getenv('ZAPI_ENABLED', '')
    app.config['ZAPI_INSTANCE_ID'] = os.getenv('ZAPI_INSTANCE_ID', '')
    app.config['ZAPI_TOKEN'] = os.getenv('ZAPI_TOKEN', '')
    app.config['ZAPI_CLIENT_TOKEN'] = os.getenv('ZAPI_CLIENT_TOKEN', '')
    app.config['ZAPI_BASE_URL'] = os.getenv('ZAPI_BASE_URL', 'https://api.z-api.io')
    app.config['ZAPI_WEBHOOK_SECRET'] = os.getenv('ZAPI_WEBHOOK_SECRET', '')
    app.config['WHATSAPP_BRIDGE_URL'] = os.getenv('WHATSAPP_BRIDGE_URL', 'http://127.0.0.1:3100')
    app.config['WHATSAPP_SEND_DELAY'] = os.getenv('WHATSAPP_SEND_DELAY', '1.2')

    os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    migrate.init_app(app, db)

    from .models import AdminUser, SiteSettings

    @login_manager.user_loader
    def load_user(user_id):
        try:
            parts = str(user_id).split(':', 1)
            user = db.session.get(AdminUser, int(parts[0]))
            # Existing signed sessions stay valid until the first credential change.
            version = int(parts[1]) if len(parts) == 2 else 1
        except (TypeError, ValueError):
            return None
        if user and user.is_active and user.session_version == version:
            return user
        return None

    from .public.routes import public_bp
    from .admin.routes import admin_bp
    from .admin.users import users_bp
    from .api.routes import api_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(users_bp, url_prefix='/admin/usuarios')
    app.register_blueprint(api_bp, url_prefix='/api')

    app.jinja_env.filters['currency_br'] = format_currency
    app.jinja_env.filters['phone_br'] = format_phone

    @app.route('/media/<path:filename>')
    def uploaded_media(filename):
        return send_from_directory(app.config['UPLOAD_DIR'], filename)

    @app.context_processor
    def inject_global_settings():
        settings = SiteSettings.query.first()

        def media_url(file_path):
            if not file_path:
                return ''
            if str(file_path).startswith(('http://', 'https://', '/')):
                return file_path
            filename = str(file_path).split('/')[-1]
            return url_for('uploaded_media', filename=filename)

        return {'site_settings': settings, 'media_url': media_url, 'format_currency': format_currency, 'format_phone': format_phone}

    with app.app_context():
        db.create_all()
        _sync_schema(app)

        # Apply this additive catalog release once, including on existing databases.
        from .gift_catalog import seed_gift_catalog
        seed_gift_catalog()

        # Mantém o acesso administrativo sincronizado com as variáveis do Railway.
        # Antes, ADMIN_EMAIL/ADMIN_PASSWORD só eram usados pelo seed na primeira criação
        # do usuário; mudanças posteriores nas env vars não atualizavam o hash salvo no banco.
        env_admin_email = os.getenv('ADMIN_EMAIL')
        env_admin_password = os.getenv('ADMIN_PASSWORD')
        if env_admin_email and env_admin_password:
            normalized_email = env_admin_email.strip().lower()
            admin_user = AdminUser.query.filter_by(is_primary=True).order_by(AdminUser.id).first()
            if admin_user is None:
                admin_user = AdminUser.query.filter(db.func.lower(AdminUser.email) == normalized_email).first()

            if admin_user is None:
                # Se já existe um único admin criado por uma configuração antiga, reutiliza-o
                # para não deixar uma conta órfã ao trocar o e-mail nas variáveis.
                if AdminUser.query.count() == 1:
                    admin_user = AdminUser.query.first()

            if admin_user is None:
                admin_user = AdminUser(name='Administrador', email=normalized_email)
                db.session.add(admin_user)
            else:
                admin_user.email = normalized_email
            admin_user.is_primary = True
            admin_user.role = 'admin'
            admin_user.enabled = True

            # A variável de ambiente é a fonte de verdade para a senha administrativa.
            # Atualizar o hash no boot garante que uma alteração no Railway passe a valer
            # imediatamente após o redeploy.
            if not admin_user.password_hash or not admin_user.check_password(env_admin_password):
                admin_user.set_password(env_admin_password)

            db.session.commit()

    return app
