import tempfile
import unittest
from pathlib import Path

from app import create_app
from app.extensions import db


class RadarTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database = Path(self.tmp.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
            "DATA_DIR": self.tmp.name,
        })
        with self.app.app_context():
            db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dashboard_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health").json["status"], "ok")

    def test_opportunity_crm_flow(self):
        response = self.client.post("/api/opportunities", json={
            "company": "Empresa Teste", "sector": "Logística", "origin": "Paraguai",
            "project": "Novo depósito", "city": "Minga Guazú", "department": "Alto Paraná",
            "event": "NEW_WAREHOUSE", "score": 91, "evidence": "Fonte pública verificada",
            "products": ["Porta seccional"],
        })
        self.assertEqual(response.status_code, 201)
        opportunity_id = response.json["id"]
        self.assertEqual(response.json["level"], "HOT")
        updated = self.client.patch(f"/api/opportunities/{opportunity_id}", json={"status": "QUALIFICADO"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["status"], "QUALIFICADO")
        timeline = self.client.get(f"/api/timeline/{opportunity_id}")
        self.assertEqual(timeline.status_code, 200)
        self.assertGreaterEqual(len(timeline.json), 2)


if __name__ == "__main__":
    unittest.main()
