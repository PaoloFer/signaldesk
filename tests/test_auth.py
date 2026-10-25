import tempfile
import unittest
from pathlib import Path

from app import database
from app.auth import authenticate, hash_password, logout, register, verify_password


class AuthenticationTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "auth.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_password_hash_is_salted_and_verifiable(self):
        first = hash_password("password-molto-sicura")
        second = hash_password("password-molto-sicura")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("password-molto-sicura", first))
        self.assertFalse(verify_password("password-errata", first))

    def test_first_user_claims_existing_workspace(self):
        user, token = register("owner@example.com", "password-molto-sicura", "Studio Test")
        self.assertTrue(database.user_can_access_project(user["id"], 1))
        self.assertEqual(authenticate(token)["email"], "owner@example.com")
        logout(token)
        self.assertIsNone(authenticate(token))

    def test_second_organization_cannot_access_first_projects(self):
        first, _ = register("first@example.com", "password-molto-sicura", "Prima")
        second, _ = register("second@example.com", "password-molto-sicura", "Seconda")
        self.assertTrue(database.user_can_access_project(first["id"], 1))
        self.assertFalse(database.user_can_access_project(second["id"], 1))
        second_projects = database.list_projects(second["id"])
        self.assertEqual(len(second_projects), 1)
        self.assertNotEqual(second_projects[0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
