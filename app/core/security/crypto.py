import pyotp
from cryptography.fernet import Fernet

from app.core.config.settings import settings

_fernet = Fernet(settings.data_encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="LEAMSE")


def verify_totp(secret: str, code: str) -> bool:
    return bool(code) and code.isdigit() and pyotp.TOTP(secret).verify(code, valid_window=1)
