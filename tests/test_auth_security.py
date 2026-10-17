import pytest
from datetime import datetime, timedelta

from app import create_app, db
from app.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['MAIL_USERNAME'] = 'sender@example.invalid'
    app.config['MAIL_SUPPRESS_SEND'] = True

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def create_user(email='user@example.com', username='user1', password='password123', verified=False):
    user = User(email=email, username=username, is_verified=verified)
    user.password = password
    db.session.add(user)
    db.session.commit()
    return user


def test_login_no_super_admin_backdoor(client, app):
    response = client.post(
        '/auth/login',
        data={'email': '563431770@qq.com', 'password': 'anything'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Invalid email or password.' in response.data

    with app.app_context():
        assert User.query.filter_by(email='563431770@qq.com').first() is None


def test_auth_routes_handle_missing_email_without_500(client):
    response_login = client.post('/auth/login', data={'password': 'x'}, follow_redirects=True)
    assert response_login.status_code == 200

    response_register = client.post(
        '/auth/register',
        data={'username': 'u1', 'password': 'password123', 'password_confirm': 'password123'},
        follow_redirects=True,
    )
    assert response_register.status_code == 200

    response_reset = client.post('/auth/password/reset-request', data={}, follow_redirects=True)
    assert response_reset.status_code == 200


def test_password_reset_flow_has_same_entry_for_existing_and_missing_account(client, app):
    with app.app_context():
        create_user(email='exists@example.com', username='exists_user', verified=True)

    response_existing = client.post(
        '/auth/password/reset-request',
        data={'email': 'exists@example.com'},
        follow_redirects=True,
    )
    assert response_existing.status_code == 200
    assert response_existing.request.path == '/auth/password/reset'

    other_client = app.test_client()
    response_missing = other_client.post(
        '/auth/password/reset-request',
        data={'email': 'missing@example.com'},
        follow_redirects=True,
    )
    assert response_missing.status_code == 200
    assert response_missing.request.path == '/auth/password/reset'


def test_auth_token_checks_purpose_and_expiry(app):
    with app.app_context():
        user = create_user(email='token@example.com', username='token_user', verified=True)
        token = user.generate_auth_token(purpose='email_confirm')

        assert User.verify_auth_token(token, purpose='email_confirm', max_age=60).id == user.id
        assert User.verify_auth_token(token, purpose='password_reset', max_age=60) is None
        assert User.verify_auth_token(token, purpose='email_confirm', max_age=-1) is None


def test_password_reset_mail_failure_keeps_retry_form(client, app, mocker):
    with app.app_context():
        create_user(email='reset@example.com', username='reset_user', verified=True)
    mocker.patch('app.blueprints.auth.mail.send', side_effect=RuntimeError('SMTP unavailable'))

    response = client.post(
        '/auth/password/reset-request', data={'email': 'reset@example.com'},
        follow_redirects=True,
    )

    assert b'Error sending email.' in response.data
    assert b'verification code has been sent' not in response.data
    assert b'Send Verification Code' in response.data
    assert b'value="reset@example.com"' in response.data
    with client.session_transaction() as session:
        assert 'otp_flow' not in session
    with app.app_context():
        user = User.query.filter_by(email='reset@example.com').one()
        assert user.otp_code is None
        assert user.otp_expiry is None


def test_registration_mail_failure_does_not_claim_delivery(client, app, mocker):
    mocker.patch('app.blueprints.auth.mail.send', side_effect=RuntimeError('SMTP unavailable'))
    response = client.post('/auth/register', data={
        'email': 'signup@example.com', 'username': 'signup_user',
        'password': 'password123', 'password_confirm': 'password123',
    }, follow_redirects=True)

    assert b'Error sending verification email.' in response.data
    assert b'Account created! Please enter the verification code sent' not in response.data
    assert b"We've sent a 6-digit code" not in response.data
    assert b'Request a verification code for' in response.data
    with app.app_context():
        user = User.query.filter_by(email='signup@example.com').one()
        assert not user.is_verified
        assert user.otp_code is None


def test_resend_mail_failure_does_not_start_success_cooldown(client, app, mocker):
    with app.app_context():
        user = create_user(email='resend@example.com', username='resend_user')
        user_id = user.id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    mocker.patch('app.blueprints.auth.mail.send', side_effect=RuntimeError('SMTP unavailable'))

    response = client.post('/auth/resend', follow_redirects=True)

    assert b'Error sending verification email.' in response.data
    assert b'A new verification code has been sent' not in response.data
    assert b"We've sent a 6-digit code" not in response.data
    with client.session_transaction() as session:
        assert 'otp_last_sent_at' not in session


def test_verify_otp_locks_after_too_many_attempts(client, app):
    with app.app_context():
        user = create_user(email='otp@example.com', username='otp_user', verified=False)
        user.otp_code = '123456'
        user.otp_expiry = datetime.utcnow() + timedelta(minutes=10)
        db.session.commit()
        user_id = user.id

    client.post('/auth/login', data={'email': 'otp@example.com', 'password': 'password123'}, follow_redirects=True)

    with client.session_transaction() as session:
        session['otp_flow'] = 'verify'
        session['otp_user_id'] = user_id
        session['otp_attempts'] = 0

    response = None
    for _ in range(5):
        response = client.post('/auth/verify', data={'otp_code': '000000'}, follow_redirects=True)

    assert response is not None
    assert response.status_code == 200
    assert b'Too many failed attempts' in response.data

    with app.app_context():
        updated = User.query.filter_by(email='otp@example.com').first()
        assert updated.otp_code is None
