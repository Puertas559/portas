import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import Company, Evidence, Opportunity, OpportunityScore, Project, ProspectSignal, ScoreFactor, Source, SourceDocument, Tenant, User, WebsiteAnalysis
from app.services.collector import analyze
from app.services.intelligence import freshness_score
from app.tenant import bootstrap_tenant


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
            self.tenant_id = bootstrap_tenant().id
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
        follow_up = self.client.patch(f"/api/opportunities/{opportunity_id}", json={"contactVerified": True, "nextActionAt": "2026-08-20T12:00:00"})
        self.assertEqual(follow_up.status_code, 200)
        self.assertTrue(follow_up.json["contactVerified"])
        self.assertTrue(follow_up.json["nextActionAt"].startswith("2026-08-20"))
        today = self.client.get("/api/dashboard/today")
        self.assertEqual(today.status_code, 200)
        self.assertGreaterEqual(len(today.json["tasks"]), 1)
        task_id = today.json["tasks"][0]["id"]
        self.assertEqual(self.client.patch(f"/api/tasks/{task_id}", json={"status": "DONE"}).status_code, 200)

        visit = self.client.post("/api/visits", json={
            "opportunityId": opportunity_id, "measurements": "Vano 4 x 5 m",
            "needs": "Reducir tiempo de carga", "notes": "Acceso con alto flujo",
            "nextStep": "Preparar propuesta",
        })
        self.assertEqual(visit.status_code, 201)
        proposal = self.client.post(f"/api/proposals/{opportunity_id}", json={
            "amount": 12500, "validityDays": 15,
            "scope": "Puerta seccional, instalación y puesta en marcha.",
        })
        self.assertEqual(proposal.status_code, 201)
        download = self.client.get(proposal.json["downloadUrl"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "application/pdf")
        download.close()
        metrics = self.client.get("/api/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json["proposals"], 1)
        self.assertEqual(metrics.json["pipelineValue"], 12500)
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
                tenant_id=self.tenant_id,
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
                tenant_id=self.tenant_id,
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
        self.assertEqual(qualified.json["opportunity"]["email"], "ventas@friodemo.com.py")
        self.assertEqual(qualified.json["opportunity"]["whatsapp"], "+595981123456")

        repeated = self.client.post(f"/api/website-analysis/{analysis_id}/qualify")
        self.assertEqual(repeated.status_code, 200)
        with self.app.app_context():
            self.assertEqual(Opportunity.query.count(), 1)
            self.assertEqual(db.session.get(Opportunity, payload["opportunityId"]).status, "QUALIFICADO")

    def test_website_analysis_can_be_disqualified(self):
        with self.app.app_context():
            analysis = WebsiteAnalysis(
                tenant_id=self.tenant_id,
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

    def test_geographic_company_search_and_crm_add(self):
        discovered = [{
            "sourceId": "osm-node-10", "company": "Industria Regional", "sector": "manufactura",
            "city": "Capiatá", "region": "Central", "address": "Ruta 2, Capiatá, Paraguay",
            "website": "https://industria.example", "phone": "+595 981 222 333",
            "email": "compras@industria.example", "linkedin": None, "score": 80,
            "source": "OpenStreetMap",
        }]
        with patch("app.services.company_search.search_companies", return_value=discovered):
            response = self.client.get("/api/company-search?city=Capiata&industry=manufactura")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["count"], 1)

        created = self.client.post("/api/company-search/add", json=discovered[0])
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["company"], "Industria Regional")
        self.assertEqual(created.json["status"], "NOVO")
        self.assertEqual(created.json["phone"], "+595 981 222 333")
        self.assertEqual(created.json["email"], "compras@industria.example")
        self.assertTrue(created.json["painPoints"])

    def test_entity_project_source_and_evidence_deduplication(self):
        base = {
            "company": "ABC S.A.", "sector": "Industria y manufactura", "origin": "Brasil",
            "website": "https://abc.com.py", "project": "Nueva planta Minga Guazú",
            "projectType": "NEW_FACTORY", "city": "Minga Guazú", "department": "Alto Paraná",
            "event": "NEW_FACTORY", "score": 82, "intent": 84, "icpFit": 90,
            "dataConfidence": 88, "products": ["Puertas seccionales"],
        }
        first = self.client.post("/api/opportunities", json={
            **base, "evidence": "La empresa anunció una nueva planta.",
            "sourceName": "Fuente oficial", "sourceUrl": "https://official.example/abc-planta",
        })
        second = self.client.post("/api/opportunities", json={
            **base, "company": "ABC SA", "event": "CONSTRUCTION_START",
            "evidence": "Comenzaron las obras de la misma planta.",
            "sourceName": "Diario industrial", "sourceUrl": "https://news.example/abc-obras",
        })
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        with self.app.app_context():
            self.assertEqual(Company.query.count(), 1)
            self.assertEqual(Project.query.count(), 1)
            self.assertEqual(Source.query.count(), 2)
            self.assertEqual(SourceDocument.query.count(), 2)
            self.assertEqual(Evidence.query.count(), 2)
            self.assertEqual(Opportunity.query.count(), 2)

    def test_explainable_scoring_and_traceable_real_world_chain(self):
        response = self.client.post("/api/opportunities", json={
            "company": "Indústria Brasil MZ", "origin": "Brasil", "website": "https://industria-mz.example",
            "project": "Planta industrial Minga Guazú", "projectType": "NEW_FACTORY",
            "city": "Minga Guazú", "department": "Alto Paraná", "country": "Paraguay",
            "event": "NEW_INVESTMENT", "sourceName": "Comunicado empresarial",
            "sourceUrl": "https://industria-mz.example/inversion-paraguay",
            "evidence": "La empresa anunció una inversión de USD 20 millones para construir una planta industrial.",
            "evidenceClassification": "FACT", "investmentAmount": 20000000,
            "investmentCurrency": "USD", "buyingStage": "PROJECT_PLANNING",
            "potentialDealValue": 180000, "probability": 35,
            "icpFit": 92, "intent": 88, "timing": 90, "projectValueFit": 96,
            "productFit": 91, "geographicFit": 100, "dataConfidence": 90,
            "signalRecency": 98, "commercialHistory": 40,
            "products": ["Puertas seccionales", "Puertas rápidas"],
        })
        self.assertEqual(response.status_code, 201)
        intelligence = self.client.get(f"/api/opportunities/{response.json['id']}/intelligence")
        self.assertEqual(intelligence.status_code, 200)
        self.assertEqual(len(intelligence.json["score"]["factors"]), 9)
        self.assertEqual(intelligence.json["evidence"][0]["classification"], "FACT")
        self.assertEqual(len(intelligence.json["productMatches"]), 2)
        self.assertEqual(response.json["buyingStage"], "PROJECT_PLANNING")
        self.assertEqual(response.json["expectedRevenue"], 63000)
        dashboard = self.client.get("/api/dashboard/revenue-intelligence")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json["pipelineGenerated"], 180000)
        with self.app.app_context():
            self.assertEqual(OpportunityScore.query.count(), 1)
            self.assertEqual(ScoreFactor.query.count(), 9)

    def test_authentication_and_role_permission(self):
        with self.app.app_context():
            db.session.add(User(
                tenant_id=self.tenant_id, name="Vendedor", email="sales@example.com",
                normalized_email="sales@example.com", password_hash=generate_password_hash("safe-test-password"),
                role="SALES",
            ))
            db.session.commit()
        self.app.config["AUTH_REQUIRED"] = True
        self.assertEqual(self.client.get("/api/opportunities").status_code, 401)
        login = self.client.post("/api/auth/login", json={"email": "sales@example.com", "password": "safe-test-password"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get("/api/opportunities").status_code, 200)
        self.assertEqual(self.client.post("/api/collector/run").status_code, 403)

    def test_tenant_isolation(self):
        with self.app.app_context():
            other = Tenant(name="Otra Industria", slug="otra-industria", settings={})
            db.session.add(other)
            db.session.flush()
            db.session.add_all([
                User(tenant_id=self.tenant_id, name="Usuario Uno", email="one@example.com", normalized_email="one@example.com", password_hash=generate_password_hash("password-one"), role="ADMIN"),
                User(tenant_id=other.id, name="Usuario Dos", email="two@example.com", normalized_email="two@example.com", password_hash=generate_password_hash("password-two"), role="ADMIN"),
            ])
            db.session.commit()
        self.app.config["AUTH_REQUIRED"] = True
        self.client.post("/api/auth/login", json={"email": "one@example.com", "password": "password-one"})
        created = self.client.post("/api/opportunities", json={
            "company": "Visible solo tenant uno", "project": "Proyecto tenant uno", "city": "Asunción",
            "department": "Central", "event": "NEW_PROJECT", "score": 70,
            "evidence": "Fuente pública tenant uno", "sourceUrl": "https://example.com/tenant-one",
        })
        self.assertEqual(created.status_code, 201)
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"workspace": "otra-industria", "email": "two@example.com", "password": "password-two"})
        self.assertEqual(self.client.get("/api/opportunities").json, [])
        self.assertEqual(self.client.get("/api/companies").json["total"], 0)

    def test_signal_freshness_and_low_confidence_hot_guard(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        self.assertEqual(freshness_score(now, now=now), 100)
        self.assertEqual(freshness_score(now - timedelta(days=45), now=now), 60)
        response = self.client.post("/api/opportunities", json={
            "company": "Empresa evidencia débil", "project": "Proyecto ambiguo", "city": "Luque",
            "department": "Central", "event": "OTHER", "evidence": "Referencia no confirmada",
            "sourceUrl": "https://example.com/weak", "icpFit": 100, "intent": 100, "timing": 100,
            "projectValueFit": 100, "productFit": 100, "geographicFit": 100,
            "dataConfidence": 25, "signalRecency": 100, "commercialHistory": 100,
        })
        self.assertEqual(response.status_code, 201)
        self.assertLess(response.json["score"], 75)
        self.assertNotEqual(response.json["level"], "HOT")

    def test_source_domain_is_not_company_identity(self):
        for company in ("Empresa Alfa", "Empresa Beta"):
            response = self.client.post("/api/opportunities", json={
                "company": company, "project": f"Proyecto {company}", "city": "Asunción",
                "department": "Central", "event": "INVESTMENT", "score": 65,
                "evidence": f"Noticia referente a {company}", "sourceName": "Mismo diario",
                "sourceUrl": f"https://news.example/{company.split()[-1].lower()}",
            })
            self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            self.assertEqual(Company.query.count(), 2)


if __name__ == "__main__":
    unittest.main()
