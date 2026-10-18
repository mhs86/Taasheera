from unittest.mock import Mock

import boto3
from botocore.config import Config
from botocore.stub import Stubber
import pytest

from app.mailer import MailSettings, SesResetSender, otp_message


def test_ses_configuration_is_explicit_and_does_not_require_smtp(monkeypatch):
    monkeypatch.setenv('RESET_MAIL_PROVIDER', 'ses')
    monkeypatch.setenv('SES_FROM_EMAIL', 'sharafm032@gmail.com')
    settings = MailSettings.from_environment()
    assert settings.provider == 'ses' and settings.region == 'us-east-1'
    assert not settings.username and not settings.password


@pytest.mark.parametrize('name,value', [('SES_FROM_EMAIL', 'invalid'), ('SES_REGION', 'eu-west-1'), ('RESET_MAIL_PROVIDER', 'invalid')])
def test_bad_ses_settings_fail_startup(monkeypatch, name, value):
    monkeypatch.setenv('RESET_MAIL_PROVIDER', 'ses')
    monkeypatch.setenv('SES_FROM_EMAIL', 'sharafm032@gmail.com')
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        MailSettings.from_environment()


def test_ses_sender_uses_official_api_and_scoped_sender_without_static_credentials(monkeypatch):
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    client = boto3.client('sesv2', region_name='us-east-1', aws_access_key_id='synthetic-key', aws_secret_access_key='synthetic-secret')
    factory = Mock(return_value=client)
    monkeypatch.setattr('boto3.client', factory)
    code = '012345'
    expected = {
        'FromEmailAddress': 'sharafm032@gmail.com',
        'Destination': {'ToAddresses': ['specimen@example.com']},
        'Content': {'Simple': {
            'Subject': {'Data': 'Your Taasheera password-reset code', 'Charset': 'UTF-8'},
            'Body': {'Text': {'Data': otp_message(code), 'Charset': 'UTF-8'}},
        }},
    }
    with Stubber(client) as stub:
        stub.add_response('send_email', {'MessageId': 'synthetic-message-id'}, expected)
        SesResetSender(MailSettings('', '', 'sharafm032@gmail.com', provider='ses')).send_reset('specimen@example.com', code)
        stub.assert_no_pending_responses()
    args, kwargs = factory.call_args
    assert args == ('sesv2',) and kwargs['region_name'] == 'us-east-1'
    assert isinstance(kwargs['config'], Config)
    assert kwargs['config'].retries['total_max_attempts'] == 1
    assert 'aws_secret_access_key' not in kwargs
