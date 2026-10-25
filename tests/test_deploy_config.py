import tempfile
import unittest
from pathlib import Path

from scripts.check_deploy_config import validate


class DeployConfigurationTest(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".env.production"
        path.write_text(content, encoding="utf-8")
        return path

    def test_accepts_complete_https_configuration(self):
        path = self.write_config(
            "\n".join((
                "DEPLOY_DOMAIN=signals.example.org",
                "ACME_EMAIL=admin@signals.example.org",
                "POSTGRES_DB=signaldesk",
                "POSTGRES_USER=signaldesk",
                "POSTGRES_PASSWORD=a-very-long-production-password",
                "PSEUDONYM_SALT=a-random-pseudonym-secret-with-32-characters",
                "COOKIE_SECURE=true",
                "PUBLIC_ORIGIN=https://signals.example.org",
                "ALLOWED_HOSTS=signals.example.org,localhost,app",
            ))
        )
        self.assertEqual(validate(path), [])

    def test_rejects_placeholders_and_insecure_cookie(self):
        path = self.write_config(
            "DEPLOY_DOMAIN=signaldesk.example.com\nCOOKIE_SECURE=false\n"
        )
        errors = validate(path)
        self.assertTrue(any("DEPLOY_DOMAIN" in error for error in errors))
        self.assertTrue(any("COOKIE_SECURE" in error for error in errors))

    def test_public_preview_requires_youtube_key(self):
        path = self.write_config(
            "\n".join((
                "DEPLOY_DOMAIN=signals.example.org",
                "ACME_EMAIL=admin@signals.example.org",
                "POSTGRES_DB=signaldesk",
                "POSTGRES_USER=signaldesk",
                "POSTGRES_PASSWORD=a-very-long-production-password",
                "PSEUDONYM_SALT=a-random-pseudonym-secret-with-32-characters",
                "COOKIE_SECURE=true",
                "PUBLIC_ORIGIN=https://signals.example.org",
                "ALLOWED_HOSTS=signals.example.org,localhost,app",
                "PUBLIC_PREVIEW_ENABLED=true",
                "YOUTUBE_API_KEY=",
            ))
        )
        self.assertTrue(any("YOUTUBE_API_KEY" in error for error in validate(path)))


if __name__ == "__main__":
    unittest.main()
