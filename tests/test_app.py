import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Opportunity, ProspectSignal, WebsiteAnalysis
from app.services.collector import analyze


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

    def test_automatic_prospecting_scoring_and_approval(self):
        score, level, event_type, products, reasons = analyze({
            "company": "Industria Demo", "title": "Nueva fábrica y centro logístico en Alto Paraná",
            "summary": "Inversión industrial para ampliar la capacidad en Paraguay",
            "source": {"name": "Fuente oficial", "type": "OFFICIAL", "reliability": 95},
        })
        self.assertGreaterEqual(score, 68)
        self.assertIn(level, {"HIGH", "HOT"})
        self.assertTrue(products)
        with self.app.app_context():
            signal = ProspectSignal(
                fingerprint="a" * 64, company_name="Industria Demo", title="Nueva fábrica en Alto Paraná",
                summary="Inversión industrial confirmada por una fuente pública.", source_name="Fuente oficial",
                source_url="https://example.com/evidencia", source_type="OFFICIAL", source_reliability=95,
                event_type=event_type, score=score, level=level, products=products, reasons=reasons,
            )
            db.session.add(signal)
            db.session.commit()
            signal_id = signal.id
        approved = self.client.post(f"/api/signals/{signal_id}/approve")
        self.assertEqual(approved.status_code, 201)
        self.assertEqual(approved.json["signal"]["status"], "APPROVED")

    def test_website_analysis_flow(self):
        sample = """<html><head><title>Frío Demo Paraguay</title></head><body>
        <h1>Planta frigorífica y centro de distribución</h1>
        <p>Ampliación de cámaras frías, muelles de carga y área de producción.</p>
        <p>Dirección: Ruta 2 km 18, Capiatá, Paraguay</p>
        <p>Gerente comercial: Ana López</p>
        <p>ventas@friodemo.com.py +595 981 123 456</p>
        <a href="https://wa.me/595981123456">WhatsApp</a>
        </body></html>"""
        with patch("app.services.site_analyzer._normalize_url", return_value="https://friodemo.com.py"), patch("app.services.site_analyzer._fetch_page", return_value=(sample, "https://friodemo.com.py")):
            response = self.client.post("/api/website-analysis", json={"url": "friodemo.com.py"})
        self.assertEqual(response.status_code, 201)
        self.assertGreaterEqual(response.json["score"], 68)
        self.assertIn("Puertas rápidas frigoríficas", response.json["products"])
        self.assertIn("ventas@friodemo.com.py", response.json["emails"])

    def test_website_analysis_qualification_creates_crm_and_messages(self):
        with self.app.app_context():
            analysis = WebsiteAnalysis(
                url="https://friodemo.com.py",
                company_name="Frío Demo Paraguay",
                sector="Frigorífico y logística",
                address="Ruta 2 km 18, Capiatá",
                phones=["+595 981 123 456"],
                whatsapp="+595981123456",
                emails=["ventas@friodemo.com.py"],
                contacts=["Ana López"],
                company_size="Mediana",
                potential_score=88,
                potential_level="ALTO",
                products=["Puertas rápidas frigoríficas", "Niveladoras de muelle"],
                services=["Instalación", "Mantenimiento preventivo"],
                reasons=["Opera cámaras frías y muelles de carga"],
                pages_analyzed=4,
                summary="Empresa con operación frigorífica y logística.",
            )
            db.session.add(analysis)
            db.session.commit()
            analysis_id = analysis.id

        qualified = self.client.post(f"/api/website-analysis/{analysis_id}/qualify")
        self.assertEqual(qualified.status_code, 201)
        payload = qualified.json["analysis"]
        self.assertEqual(payload["decision"], "QUALIFIED")
        self.assertIsNotNone(payload["opportunityId"])
        self.assertIn("Frío Demo Paraguay", payload["whatsappMessage"])
        self.assertIn("Puertas Brasil PY", payload["emailBody"])

        repeated = self.client.post(f"/api/website-analysis/{analysis_id}/qualify")
        self.assertEqual(repeated.status_code, 200)
        with self.app.app_context():
            self.assertEqual(Opportunity.query.count(), 1)
            self.assertEqual(db.session.get(Opportunity, payload["opportunityId"]).status, "QUALIFICADO")

    def test_website_analysis_can_be_disqualified(self):
        with self.app.app_context():
            analysis = WebsiteAnalysis(
                url="https://servicios-demo.com.py",
                company_name="Servicios Demo",
                potential_score=20,
                potential_level="BAJO",
            )
            db.session.add(analysis)
            db.session.commit()
            analysis_id = analysis.id

        response = self.client.post(f"/api/website-analysis/{analysis_id}/disqualify")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["decision"], "DISQUALIFIED")


if __name__ == "__main__":
    unittest.main()
