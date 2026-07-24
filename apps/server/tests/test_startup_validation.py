"""Unit tests for production startup config validation (agentcore.main).

Focus: the fail-closed guards in ``_validate_production_security``. The byok
master-key guard (安全权限与治理.md §七) is the one that matters most — it turns a
missing/malformed ``ENCRYPTION_KEY`` from a silent "boots green but can't chat"
landmine into a boot refusal, since byok makes a per-user key (and thus at-rest
encryption) mandatory.
"""

import pytest

from agentcore.config import settings
from agentcore.main import _validate_production_security

# A valid 64-hex (32-byte) AES-256 master key.
_MASTER_KEY = "a" * 64
# A JWT secret that isn't a known placeholder, so the JWT guard passes.
_GOOD_JWT = "x" * 48


@pytest.fixture
def prod_settings(monkeypatch):
    """Non-debug settings with the JWT + cookie guards already satisfied, so each
    test can isolate one dimension (here: the encryption key)."""
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "jwt_secret_key", _GOOD_JWT)
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "cookie_samesite", "none")
    return settings


def test_debug_skips_all_validation(monkeypatch):
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "encryption_key", "")
    # No raise even with everything misconfigured — debug bypasses the guard.
    _validate_production_security()


def test_byok_without_master_key_refuses_boot(prod_settings, monkeypatch):
    monkeypatch.setattr(prod_settings, "billing_mode", "byok")
    monkeypatch.setattr(prod_settings, "encryption_key", "")
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is unset"):
        _validate_production_security()


def test_byok_with_malformed_master_key_refuses_boot(prod_settings, monkeypatch):
    monkeypatch.setattr(prod_settings, "billing_mode", "byok")
    monkeypatch.setattr(prod_settings, "encryption_key", "not-hex")
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is malformed"):
        _validate_production_security()


def test_byok_with_valid_master_key_boots(prod_settings, monkeypatch):
    monkeypatch.setattr(prod_settings, "billing_mode", "byok")
    monkeypatch.setattr(prod_settings, "encryption_key", _MASTER_KEY)
    _validate_production_security()  # no raise


def test_platform_mode_tolerates_missing_master_key(prod_settings, monkeypatch):
    # Optional credential under platform billing → fail-safe, not fail-closed.
    monkeypatch.setattr(prod_settings, "billing_mode", "platform")
    monkeypatch.setattr(prod_settings, "encryption_key", "")
    _validate_production_security()  # no raise


def test_platform_mode_malformed_master_key_refuses_boot(prod_settings, monkeypatch):
    # A non-empty but invalid ENCRYPTION_KEY must refuse boot in any billing mode —
    # otherwise BYOK / MFA paths hit binascii 500s at runtime.
    monkeypatch.setattr(prod_settings, "billing_mode", "platform")
    monkeypatch.setattr(prod_settings, "encryption_key", "not-hex")
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is malformed"):
        _validate_production_security()


def test_cloud_code_execute_without_ack_refuses_boot(prod_settings, monkeypatch):
    """SEC-005: enabling cloud code_execute (RCE in the API container) without the
    explicit unsafe acknowledgement must fail closed, so a single flag can't expose it."""
    monkeypatch.setattr(prod_settings, "billing_mode", "platform")
    monkeypatch.setattr(prod_settings, "code_execute_cloud_enabled", True)
    monkeypatch.setattr(prod_settings, "code_execute_cloud_unsafe_ack", False)
    with pytest.raises(RuntimeError, match="CODE_EXECUTE_CLOUD_ENABLED"):
        _validate_production_security()


def test_cloud_code_execute_with_ack_boots(prod_settings, monkeypatch):
    """The deliberate second flag (CODE_EXECUTE_CLOUD_UNSAFE_ACK) lets an operator who
    has a real sandbox in front opt in explicitly."""
    monkeypatch.setattr(prod_settings, "billing_mode", "platform")
    monkeypatch.setattr(prod_settings, "code_execute_cloud_enabled", True)
    monkeypatch.setattr(prod_settings, "code_execute_cloud_unsafe_ack", True)
    _validate_production_security()  # no raise


def test_cloud_code_execute_default_off_boots(prod_settings, monkeypatch):
    # Default posture: cloud code_execute off → nothing to acknowledge.
    monkeypatch.setattr(prod_settings, "billing_mode", "platform")
    monkeypatch.setattr(prod_settings, "code_execute_cloud_enabled", False)
    monkeypatch.setattr(prod_settings, "code_execute_cloud_unsafe_ack", False)
    _validate_production_security()  # no raise


def test_debug_skips_cloud_code_execute_guard(monkeypatch):
    # debug bypasses every production guard, including the cloud-RCE one.
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "code_execute_cloud_enabled", True)
    monkeypatch.setattr(settings, "code_execute_cloud_unsafe_ack", False)
    _validate_production_security()  # no raise
