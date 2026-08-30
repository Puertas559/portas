import os
import unittest
from unittest.mock import patch

from scripts.check_production_env import main


SAFE_ENV = {
    "DATABASE_URL": "postgresql+psycopg://radar:StrongPass123@db.example:5432/radar",
    "SECRET_KEY": "m3tCK-7w9Zp2Qv8Lx5Nh1Fu6Da4Se0Yr9Bc7Gi2Ko8Pw3Aj6",
    "DATA_DIR": "/data",
    "AUTH_REQUIRED": "true",
    "SESSION_COOKIE_SECURE": "true",
    "ALLOW_WEB_SETUP": "false",
    "TRUST_PROXY": "true",
    "ADMIN_EMAIL": "admin@example.com",
    "ADMIN_PASSWORD": "Strong-Initial-Pass-2026",
    "BOOTSTRAP_ADMIN_COMPLETE": "false",
}


class ProductionEnvironmentTest(unittest.TestCase):
    def test_safe_environment_is_accepted(self):
        with patch.dict(os.environ, SAFE_ENV, clear=True):
            self.assertEqual(main(), 0)

    def test_unsafe_environment_is_rejected(self):
        unsafe = dict(SAFE_ENV, AUTH_REQUIRED="false", SECRET_KEY="changeme", ALLOW_WEB_SETUP="true")
        with patch.dict(os.environ, unsafe, clear=True):
            self.assertEqual(main(), 1)

    def test_admin_password_can_be_removed_after_bootstrap(self):
        ready = dict(SAFE_ENV, BOOTSTRAP_ADMIN_COMPLETE="true", ADMIN_EMAIL="", ADMIN_PASSWORD="")
        with patch.dict(os.environ, ready, clear=True):
            self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
