"""Password policy and salted PBKDF2 hashes; no password-bearing log messages."""
import hashlib
import hmac
import secrets

ITERATIONS = 600_000


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError('Password must contain between 12 and 1024 characters')


def hash_password(password):
    validate_password(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 1024:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        rounds = int(iterations)
        if algorithm != 'pbkdf2_sha256' or not 100_000 <= rounds <= ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), rounds).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
