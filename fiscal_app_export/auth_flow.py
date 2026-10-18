"""Small, dependency-free authentication policy shared by app and tests."""
import hashlib
import hmac
from urllib.parse import unquote, urlsplit

AUTH_POST_PATHS = frozenset({
    '/api/login', '/api/register', '/api/forgot-password',
    '/api/reset-password', '/api/change-password', '/api/resend-verification',
    '/api/logout',
})

def safe_auth_next(value, default='/dashboard'):
    if not isinstance(value, str) or len(value) > 2048:
        return default
    decoded = value
    for _ in range(4):
        if (not decoded.startswith('/') or decoded.startswith('//')
                or '\\' in decoded or any(ord(c) <= 32 or ord(c) == 127 for c in decoded)):
            return default
        try:
            parsed = urlsplit(decoded)
        except ValueError:
            return default
        if parsed.scheme or parsed.netloc:
            return default
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    else:
        return default
    if parsed.path.rstrip('/') in {'/login', '/signup', '/auth/google', '/auth/google/callback'}:
        return default
    return value

def session_identity(user_id, password_hash, google_id, secret):
    # Neither the password hash nor the Google subject is exposed in cookies.
    payload = f'auth-v1\0{user_id}\0{password_hash or ""}\0{google_id or ""}'
    stamp = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f'v1:{user_id}:{stamp}'

def session_user_id(value):
    if not isinstance(value, str) or len(value) > 96:
        return None
    parts = value.split(':')
    if (len(parts) != 3 or parts[0] != 'v1' or not parts[1].isascii()
            or not parts[1].isdigit() or len(parts[1]) > 19 or len(parts[2]) != 64
            or any(c not in '0123456789abcdef' for c in parts[2])):
        return None
    try:
        user_id = int(parts[1])
    except ValueError:
        return None
    return user_id if 0 < user_id <= 2**63-1 else None
