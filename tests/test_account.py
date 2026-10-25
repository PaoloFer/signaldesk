"""Test per A1 (cambio password), A4 (rate limiting) e A5 (sessioni)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import database
from app import main
from app.auth import (
    authenticate, change_password, issue_session, login, register, token_hash,
)
from app.ratelimit import RateLimitExceeded, SlidingWindowRateLimiter


class PasswordChangeTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "account.db"
        database.initialize()
        self.user, _ = register("owner@example.com", "password-iniziale-10", "Studio Test")

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_change_password_invalidates_other_sessions(self):
        token_a = issue_session(self.user["id"])
        token_b = issue_session(self.user["id"])
        self.assertTrue(
            change_password(self.user["id"], "password-iniziale-10", "nuova-password-10", keep_token=token_a)
        )
        # La sessione corrente resta valida, le altre vengono revocate.
        self.assertIsNotNone(authenticate(token_a))
        self.assertIsNone(authenticate(token_b))
        # La vecchia password non funziona più, la nuova sì.
        self.assertIsNone(login("owner@example.com", "password-iniziale-10"))
        self.assertIsNotNone(login("owner@example.com", "nuova-password-10"))

    def test_change_password_rejects_wrong_current_password(self):
        self.assertFalse(
            change_password(self.user["id"], "password-sbagliata", "nuova-password-10")
        )
        self.assertIsNotNone(login("owner@example.com", "password-iniziale-10"))

    def test_sessions_listing_and_revoke_others(self):
        token_a = issue_session(self.user["id"])
        issue_session(self.user["id"])
        # La registrazione ha già creato una sessione: totale 3.
        sessions = database.list_user_sessions(self.user["id"])
        self.assertEqual(len(sessions), 3)
        revoked = database.delete_user_sessions_except(self.user["id"], token_hash(token_a))
        self.assertEqual(revoked, 2)
        remaining = database.list_user_sessions(self.user["id"])
        self.assertEqual(len(remaining), 1)


class RateLimiterTest(unittest.TestCase):
    def test_under_threshold_requests_pass(self):
        limiter = SlidingWindowRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
        limiter.check("key")
        limiter.record_failure("key")
        limiter.record_failure("key")
        limiter.check("key")

    def test_lockout_after_threshold_and_progressive_duration(self):
        limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60, lockout_seconds=100)
        limiter.record_failure("key")
        limiter.record_failure("key")
        with self.assertRaises(RateLimitExceeded) as caught:
            limiter.check("key")
        first_retry = caught.exception.retry_after
        self.assertGreater(first_retry, 0)
        self.assertLessEqual(first_retry, 100)
        # Durante il lockout i fallimenti non estendono il blocco.
        limiter.record_failure("key")
        with self.assertRaises(RateLimitExceeded) as caught:
            limiter.check("key")
        self.assertLessEqual(caught.exception.retry_after, first_retry)

    def test_success_resets_counter(self):
        limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60, lockout_seconds=60)
        limiter.record_failure("key")
        limiter.reset("key")
        limiter.record_failure("key")
        limiter.check("key")

    def test_failures_expire_outside_window(self):
        limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=1, lockout_seconds=60)
        limiter.record_failure("key")
        limiter._failures["key"] = [stamp - 10 for stamp in limiter._failures["key"]]
        limiter.record_failure("key")
        # Un solo fallimento nella finestra: niente lockout.
        limiter.check("key")


class LoginRateLimitEndpointTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "login_limit.db"
        database.initialize()
        register("limited@example.com", "password-corretta-10", "Org")
        self.original_limiter = main.auth_rate_limiter
        main.auth_rate_limiter = SlidingWindowRateLimiter(
            max_attempts=3, window_seconds=600, lockout_seconds=600
        )

    def tearDown(self):
        main.auth_rate_limiter = self.original_limiter
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            cookies={},
            state=SimpleNamespace(user=None),
        )

    def test_repeated_failures_return_429(self):
        payload = main.AuthCredentials(email="limited@example.com", password="sbagliata-000")
        for _ in range(3):
            with self.assertRaises(HTTPException) as caught:
                main.auth_login(payload, self._request())
            self.assertEqual(caught.exception.status_code, 401)
        with self.assertRaises(HTTPException) as caught:
            main.auth_login(payload, self._request())
        self.assertEqual(caught.exception.status_code, 429)
        self.assertIn("Retry-After", caught.exception.headers)
        # Anche con la password corretta la chiave resta bloccata fino a scadenza.
        good = main.AuthCredentials(email="limited@example.com", password="password-corretta-10")
        with self.assertRaises(HTTPException) as caught:
            main.auth_login(good, self._request())
        self.assertEqual(caught.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
