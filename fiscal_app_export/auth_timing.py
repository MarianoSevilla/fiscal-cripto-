"""Bounded login phase timings; never accepts request or account data."""
from contextlib import contextmanager
import logging
from time import perf_counter
from uuid import uuid4

logger = logging.getLogger('auth.timing')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False

PHASES = frozenset({'account_lookup', 'password_check', 'verification_email',
                    'last_login_commit', 'session_create'})

class LoginTiming:
    def __init__(self):
        self.trace = uuid4().hex[:16]
        self.started = perf_counter()

    def __enter__(self):
        logger.info('AUTH_LOGIN_TIMING trace=%s event=start', self.trace)
        return self

    @contextmanager
    def phase(self, name):
        if name not in PHASES:
            raise ValueError('Unknown login timing phase')
        started = perf_counter()
        logger.info('AUTH_LOGIN_TIMING trace=%s phase=%s event=start', self.trace, name)
        try:
            yield
        finally:
            logger.info('AUTH_LOGIN_TIMING trace=%s phase=%s event=end duration_ms=%d',
                        self.trace, name, (perf_counter()-started)*1000)

    def __exit__(self, exc_type, exc, tb):
        logger.info('AUTH_LOGIN_TIMING trace=%s event=end duration_ms=%d failed=%d',
                    self.trace, (perf_counter()-self.started)*1000, exc_type is not None)
        return False
