import tempfile
import unittest
from pathlib import Path

from app import database


class ProjectIsolationTest(unittest.TestCase):
    def setUp(self):
        self.original_path = database.DB_PATH
        self.temp_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_directory.name) / "test.db"
        database.initialize()

    def tearDown(self):
        database.DB_PATH = self.original_path
        self.temp_directory.cleanup()

    def test_existing_data_is_migrated_to_default_project(self):
        projects = database.list_projects()
        self.assertEqual(projects[0]["id"], 1)
        self.assertGreater(projects[0]["contents"], 0)
        self.assertGreater(projects[0]["comments"], 0)

    def test_same_content_can_belong_to_separate_project(self):
        project = database.create_project("Ricerca separata")
        content = database.all_contents(1)[0]
        database.upsert_contents([content], project["id"])
        self.assertEqual(len(database.all_contents(project["id"])), 1)
        self.assertGreater(len(database.all_contents(1)), 1)
        self.assertEqual(database.all_comments(project["id"]), [])

    def test_deleting_project_does_not_delete_shared_default_data(self):
        project = database.create_project("Temporaneo")
        content = database.all_contents(1)[0]
        database.upsert_contents([content], project["id"])
        self.assertTrue(database.delete_project(project["id"]))
        self.assertGreater(len(database.all_contents(1)), 0)


if __name__ == "__main__":
    unittest.main()
