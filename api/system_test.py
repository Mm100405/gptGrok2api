import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import system


class SystemVersionRoutesTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(system.create_router("1.0.3"))
        self.client = TestClient(app)

    def test_update_meta_uses_github_update_service_and_forwards_force(self):
        payload = {
            "current_version": "1.0.3",
            "latest_version": "1.0.3",
            "status": "ok",
            "changelog": "# Changelog",
        }
        update_info = AsyncMock(return_value=payload)

        with patch.object(system, "get_latest_release_info", new=update_info):
            response = self.client.get("/meta/update?force=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        update_info.assert_awaited_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
