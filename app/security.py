import base64, hashlib
from cryptography.fernet import Fernet
from app.config import settings

def _fernet():
    # Derive a stable Fernet key from an app secret. Replace with a KMS for production.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.encryption_key.encode()).digest())
    return Fernet(key)

def encrypt(value: str) -> str: return _fernet().encrypt(value.encode()).decode()
def decrypt(value: str) -> str: return _fernet().decrypt(value.encode()).decode()
