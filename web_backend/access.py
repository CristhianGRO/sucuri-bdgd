"""Explicit browser pairing for the trusted Pages origin."""
import secrets
import threading
import time

PAGES_ORIGIN = 'https://cristhiangro.github.io'

class Access:
    def __init__(self):
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.renew()

    def renew(self):
        with self.lock:
            self.code = f'{secrets.randbelow(100000000):08d}'
            self.deadline = time.monotonic() + 600
            self.attempts = 0
        return self.code

    def pair(self, code):
        with self.lock:
            if self.attempts >= 5 or time.monotonic() > self.deadline:
                raise ValueError('Código expirado ou bloqueado. Gere outro no SUCURI Local.')
            self.attempts += 1
            if not isinstance(code,str) or not secrets.compare_digest(code,self.code):
                raise ValueError('Código incorreto. Confira o aplicativo local.')
            self.deadline = 0
            return self.token

    def authorized(self, authorization):
        return secrets.compare_digest(authorization or '', 'Bearer ' + self.token)
