import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.task_registry import TaskRegistry


class TaskRegistryTests(unittest.TestCase):
    def test_persists_consumed_response_ids(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "responses.json"
            TaskRegistry(path).add("response-1")

            self.assertTrue(TaskRegistry(path).contains("response-1"))


if __name__ == "__main__":
    unittest.main()
