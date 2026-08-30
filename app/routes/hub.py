from datetime import date, datetime, timezone

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import HubEvent, HubEventAccount, HubEventAction, HubEventSource, Tenant
from ..services.entity_resolution import normalize_domain, normalize_name, resolve_company
from ..services.hub_events import (
    analyze_event_account,
    apply_automatic_intelligence,
    build_playbook,
    create_detected_event,
    event_key,
    extract_company_candidates_from_url,
    extract_page,
    parse_company_text,
    run_hub_event_scan,
)
from ..tenant import current_tenant, current_user, require_permission

hub_bp = Blueprint("hub", __name__, url_prefix="/hub")

MARKETS = {
    "PY": {
        "code": "PY",
        "name": "Paraguay",
        "country": "Paraguay",
        "flag": "🇵🇾",
        "currency": "USD",
        "radarEnabled": True,
        "subtitle": "Eventos, missões e oportunidades no Paraguai",
    },
    "AR": {
        "code": "AR",
        "name": "Argentina",
        "country": "Argentina",
        "flag": "🇦🇷",
        "currency": "USD",
        "radarEnabled": False,
        "subtitle": "Eventos, missões e oportunidades na Argentina",
    },
}


def _allowed():
    tenant = current_tenant()
    return bool(tenant and tenant.slug == "puertas-brasil-py")


def _market_or_404(market_code):
    code = str(market_code or "").upper()
    market = MARKETS.get(code)
    if not market:
        abort(404)
    return market


def _event_or_404(event_id, market_code):
    tenant = current_tenant()
    market = _market_or_404(market_code)
    return HubEvent.query.filter_by(
        id=event_id, tenant_id=tenant.id, market_code=market["code"]
    ).first_or_404()


def _account_or_404(account_id, market_code):
    tenant = current_tenant()
    market = _market_or_404(market_code)
    return HubEventAccount.query.filter_by(
        id=account_id, tenant_id=tenant.id, market_code=market["code"]
    ).first_or_404()


@hub_bp.get("/enter")
def enter():
    user = current_user()
    if not user:
        abort(403)
    if user.role == "GROUP_ADMIN":
        tenant = Tenant.query.filter_by(slug="puertas-brasil-py", status="ACTIVE").first_or_404()
        session["active_tenant_id"] = tenant.id
        return redirect(url_for("hub.home"))
    if user.tenant and user.tenant.slug == "puertas-brasil-py":
        return redirect(url_for("hub.home"))
    abort(403)


@hub_bp.get("/health")
def health():
    if not _allowed():
        abort(404)
    try:
        tenant = current_tenant()
        by_market = {
            code: {
                "events": HubEvent.query.filter_by(tenant_id=tenant.id, market_code=code).count(),
                "sources": HubEventSource.query.filter_by(tenant_id=tenant.id, market_code=code).count(),
            }
            for code in MARKETS
        }
        return jsonify(
            ok=True,
            module="hub-event-intelligence",
            tenant=tenant.slug,
            markets=by_market,
            message="HUB Event Intelligence ativo e mercados isolados",
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify(ok=False, module="hub-event-intelligence", error=str(exc)), 500


@hub_bp.get("/")
def home():
    if not _allowed():
        abort(404)
    return render_template(
        "hub/index.html",
        tenant=current_tenant(),
        brand=current_tenant().settings or {},
        user=current_user(),
        market=None,
        markets=MARKETS,
    )


@hub_bp.get("/<market_code>/")
def market_home(market_code):
    if not _allowed():
        abort(404)
    market = _market_or_404(market_code)
    return render_template(
        "hub/index.html",
        tenant=current_tenant(),
        brand=current_tenant().settings or {},
        user=current_user(),
        market=market,
        markets=MARKETS,
    )


@hub_bp.get("/<market_code>/api/overview")
def overview(market_code):
    if not _allowed():
        abort(404)
    market = _market_or_404(market_code)
    t = current_tenant()
    rows = (
        HubEvent.query.filter_by(tenant_id=t.id, market_code=market["code"])
        .order_by(HubEvent.start_date.asc().nullslast(), HubEvent.created_at.desc())
        .all()
    )
    active = [x for x in rows if x.status in {"APPROVED", "PREPARATION", "EXECUTION", "FOLLOW_UP"}]
    accounts = HubEventAccount.query.filter_by(tenant_id=t.id, market_code=market["code"]).all()
    return jsonify(
        market=market,
        events=[x.to_dict() for x in rows],
        metrics={
            "detected": sum(x.status in {"DETECTED", "TRIAGE", "VALIDATED", "ANALYSIS", "MONITOR"} for x in rows),
            "active": len(active),
            "approved": sum(x.status in {"APPROVED", "PREPARATION", "EXECUTION", "FOLLOW_UP", "CLOSED"} for x in rows),
            "pipelinePotential": sum(float((x.projection or {}).get("pipelinePotential") or 0) for x in active),
            "investment": sum(float(x.cost_estimate or 0) for x in active),
            "accounts": len(accounts),
            "analyzedAccounts": sum(x.status == "ANALYZED" for x in accounts),
            "tierA": sum(x.tier == "A" for x in accounts),
        },
    )


@hub_bp.post("/<market_code>/api/events")
@require_permission("WRITE_CRM")
def create_event(market_code):
    if not _allowed():
        abort(404)
    market = _market_or_404(market_code)
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify(error="Nome obrigatório"), 400
    sd = date.fromisoformat(d["startDate"]) if d.get("startDate") else None
    row, created = create_detected_event(
        current_tenant().id,
        market["code"],
        name,
        url=d.get("url"),
        source_mode="MANUAL",
        start_date=sd,
        city=d.get("city"),
        organizer=d.get("organizer"),
        country=market["country"],
        event_type=d.get("eventType"),
        description=d.get("description"),
        confidence=90,
    )
    if created:
        row.start_date = sd
        row.city = d.get("city")
        row.organizer = d.get("organizer")
        row.event_type = d.get("eventType")
        row.description = d.get("description")
        row.currency = d.get("currency") or market["currency"]
        row.normalized_key = event_key(row.name, row.start_date, row.city, row.organizer)
    db.session.commit()
    return jsonify(event=row.to_dict(), created=created), 201 if created else 200


@hub_bp.post("/<market_code>/api/events/import-url")
@require_permission("WRITE_CRM")
def import_url(market_code):
    if not _allowed():
        abort(404)
    market = _market_or_404(market_code)
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    if not url:
        return jsonify(error="URL obrigatória"), 400
    try:
        info = extract_page(url, market_code=market["code"])
    except Exception as exc:
        return jsonify(error=f"Não foi possível ler a página: {exc}"), 422
    row, created = create_detected_event(
        current_tenant().id,
        market["code"],
        info["name"],
        url=url,
        source_mode="URL",
        start_date=info.get("startDate"),
        city=info.get("city"),
        organizer=info.get("organizer"),
        country=market["country"],
        event_type=info.get("eventType"),
        description=info.get("description"),
        confidence=70,
    )
    apply_automatic_intelligence(row, info, create_accounts=True)
    db.session.commit()
    return jsonify(event=row.to_dict(include_children=True), created=created)


@hub_bp.get("/<market_code>/api/events/<int:event_id>")
def event_detail(market_code, event_id):
    if not _allowed():
        abort(404)
    return jsonify(event=_event_or_404(event_id, market_code).to_dict(include_children=True))


@hub_bp.patch("/<market_code>/api/events/<int:event_id>")
@require_permission("WRITE_CRM")
def update_event(market_code, event_id):
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    for incoming, attr in [
        ("name", "name"), ("city", "city"), ("organizer", "organizer"), ("url", "url"),
        ("eventType", "event_type"), ("description", "description"),
        ("participationMode", "participation_mode"), ("notes", "notes"), ("currency", "currency"),
    ]:
        if incoming in d:
            setattr(row, attr, d.get(incoming))
    if "startDate" in d:
        row.start_date = date.fromisoformat(d["startDate"]) if d.get("startDate") else None
    if "endDate" in d:
        row.end_date = date.fromisoformat(d["endDate"]) if d.get("endDate") else None
    if "costEstimate" in d:
        row.cost_estimate = max(0, float(d.get("costEstimate") or 0))
    if "status" in d:
        allowed = {"DETECTED", "TRIAGE", "VALIDATED", "ANALYSIS", "APPROVED", "PREPARATION", "EXECUTION", "FOLLOW_UP", "CLOSED", "MONITOR", "DISCARDED"}
        if d["status"] not in allowed:
            return jsonify(error="Status inválido"), 400
        row.status = d["status"]
        if row.status == "APPROVED":
            row.approved_at = datetime.now(timezone.utc)
            build_playbook(row, current_user().name if current_user() else "Equipe HUB")
        if row.status == "CLOSED":
            row.closed_at = datetime.now(timezone.utc)
    row.normalized_key = event_key(row.name, row.start_date, row.city, row.organizer)
    db.session.commit()
    return jsonify(event=row.to_dict(include_children=True))


@hub_bp.post("/<market_code>/api/events/<int:event_id>/reanalyze")
@require_permission("WRITE_CRM")
def reanalyze_event(market_code, event_id):
    market = _market_or_404(market_code)
    row = _event_or_404(event_id, market_code)
    if not row.url:
        return jsonify(error="Este evento não possui URL para reanálise automática."), 400
    try:
        info = extract_page(row.url, market_code=market["code"])
    except Exception as exc:
        return jsonify(error=f"Não foi possível reanalisar a página: {exc}"), 422
    apply_automatic_intelligence(row, info, create_accounts=True)
    if row.status in {"DETECTED", "TRIAGE"}:
        row.status = "ANALYSIS"
    db.session.commit()
    return jsonify(event=row.to_dict(include_children=True))


@hub_bp.post("/<market_code>/api/events/<int:event_id>/score")
@require_permission("WRITE_CRM")
def score_event(market_code, event_id):
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    commercial = sum(max(0, min(100, int(d.get(k, 0)))) * w for k, w in {"icp": .25, "timing": .20, "decisionAccess": .15, "preAccess": .10}.items())
    economic = max(0, min(100, int(d.get("economicEfficiency", 0))))
    strategic = max(0, min(100, int(d.get("partnership", 0)))) * .5 + max(0, min(100, int(d.get("visibility", 0)))) * .5
    row.commercial_score = round(commercial / .70)
    row.economic_score = round(economic)
    row.strategic_score = round(strategic)
    row.total_score = round(commercial + economic * .20 + strategic * .10)
    previous = row.score_details or {}
    row.score_details = {
        **d,
        "automatic": False,
        "evidence": previous.get("evidence") or {},
        "analyzedAt": previous.get("analyzedAt"),
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "validatedBy": current_user().name if current_user() else None,
    }
    row.status = "ANALYSIS" if row.status in {"DETECTED", "TRIAGE", "VALIDATED"} else row.status
    db.session.commit()
    return jsonify(event=row.to_dict())


@hub_bp.post("/<market_code>/api/events/<int:event_id>/projection")
@require_permission("WRITE_CRM")
def projection(market_code, event_id):
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    relevant = max(0, int(d.get("relevantAccounts") or 0))
    meetings = max(0, int(d.get("meetings") or 0))
    visits = max(0, int(d.get("visits") or 0))
    opps = max(0, int(d.get("opportunities") or 0))
    ticket = max(0, float(d.get("averageTicket") or 0))
    probability = max(0, min(100, float(d.get("probability") or 20)))
    raw = opps * ticket
    weighted = raw * (probability / 100)
    cost = float(row.cost_estimate or 0)
    row.projection = {
        "relevantAccounts": relevant,
        "meetings": meetings,
        "visits": visits,
        "opportunities": opps,
        "averageTicket": ticket,
        "probability": probability,
        "pipelinePotential": raw,
        "weightedPipeline": weighted,
        "pipelineCostMultiple": round(raw / cost, 1) if cost else None,
    }
    db.session.commit()
    return jsonify(event=row.to_dict())


@hub_bp.post("/<market_code>/api/events/<int:event_id>/accounts")
@require_permission("WRITE_CRM")
def add_account(market_code, event_id):
    market = _market_or_404(market_code)
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    name = (d.get("companyName") or "").strip()
    if not name:
        return jsonify(error="Empresa obrigatória"), 400
    existing = HubEventAccount.query.filter_by(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id, company_name=name).first()
    if existing:
        return jsonify(account=existing.to_dict(), duplicate=True)
    a = HubEventAccount(
        tenant_id=row.tenant_id,
        market_code=market["code"],
        event_id=row.id,
        company_name=name,
        website=d.get("website"),
        role=d.get("role") or "PARTICIPANT",
        tier=d.get("tier") or "C",
        icp_score=max(0, min(100, int(d.get("icpScore") or 0))),
        contact_name=d.get("contactName"), contact_role=d.get("contactRole"),
        email=d.get("email"), whatsapp=d.get("whatsapp"), hypothesis=d.get("hypothesis"),
    )
    if market["code"] == "PY":
        domain = normalize_domain(a.website)
        from ..models import Company
        q = Company.query.filter_by(tenant_id=row.tenant_id, status="ACTIVE")
        company = q.filter_by(domain=domain).first() if domain else q.filter_by(normalized_name=normalize_name(name)).first()
        a.company_id = company.id if company else None
    db.session.add(a)
    db.session.commit()
    return jsonify(account=a.to_dict()), 201


@hub_bp.post("/<market_code>/api/events/<int:event_id>/accounts/import-text")
@require_permission("WRITE_CRM")
def import_accounts_text(market_code, event_id):
    market = _market_or_404(market_code)
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    items = parse_company_text(d.get("text") or "")
    if not items:
        return jsonify(error="Nenhuma empresa válida foi encontrada no texto."), 400
    created = duplicates = 0
    for item in items:
        name = item["companyName"]
        website = item.get("website")
        existing = HubEventAccount.query.filter_by(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id, company_name=name).first()
        if existing:
            duplicates += 1
            continue
        db.session.add(HubEventAccount(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id, company_name=name, website=website, role="PARTICIPANT", tier="C", icp_score=0, status="MAPPED"))
        created += 1
    db.session.commit()
    return jsonify(created=created, duplicates=duplicates, total=len(items))


@hub_bp.post("/<market_code>/api/events/<int:event_id>/accounts/discover-url")
@require_permission("WRITE_CRM")
def discover_accounts_url(market_code, event_id):
    market = _market_or_404(market_code)
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or row.url or "").strip()
    if not url:
        return jsonify(error="Informe a URL da lista de expositores/participantes."), 400
    try:
        items = extract_company_candidates_from_url(url)
    except Exception as exc:
        return jsonify(error=f"Não foi possível ler a lista de empresas: {exc}"), 422
    created = duplicates = 0
    for item in items:
        name = item["companyName"]
        website = item.get("website")
        existing = HubEventAccount.query.filter_by(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id, company_name=name).first()
        if existing:
            duplicates += 1
            continue
        db.session.add(HubEventAccount(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id, company_name=name, website=website, role=item.get("role") or "PARTICIPANT", tier="C", icp_score=0, status="MAPPED"))
        created += 1
    db.session.commit()
    return jsonify(created=created, duplicates=duplicates, found=len(items))


@hub_bp.post("/<market_code>/api/events/<int:event_id>/accounts/analyze")
@require_permission("WRITE_CRM")
def analyze_accounts(market_code, event_id):
    market = _market_or_404(market_code)
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    requested = d.get("accountIds") or []
    q = HubEventAccount.query.filter_by(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id)
    if requested:
        q = q.filter(HubEventAccount.id.in_([int(x) for x in requested]))
    else:
        q = q.filter(HubEventAccount.website.isnot(None), HubEventAccount.status.in_(["MAPPED", "ANALYSIS_ERROR"]))
    accounts = q.order_by(HubEventAccount.id.asc()).limit(8).all()
    if not accounts:
        return jsonify(analyzed=0, success=0, errors=0, remaining=0, message="Nenhuma empresa com site pendente de análise neste lote.")
    results = []
    success = errors = 0
    for account in accounts:
        result = analyze_event_account(account, max_pages=3)
        results.append({"id": account.id, "companyName": account.company_name, **result})
        success += int(result.get("ok"))
        errors += int(not result.get("ok"))
    db.session.commit()
    remaining = HubEventAccount.query.filter_by(tenant_id=row.tenant_id, market_code=market["code"], event_id=row.id).filter(HubEventAccount.website.isnot(None), HubEventAccount.status.in_(["MAPPED", "ANALYSIS_ERROR"])).count()
    return jsonify(analyzed=len(accounts), success=success, errors=errors, remaining=remaining, results=results)


@hub_bp.patch("/<market_code>/api/accounts/<int:account_id>")
@require_permission("WRITE_CRM")
def update_account(market_code, account_id):
    a = _account_or_404(account_id, market_code)
    d = request.get_json(silent=True) or {}
    for incoming, attr in [("tier", "tier"), ("role", "role"), ("contactName", "contact_name"), ("contactRole", "contact_role"), ("email", "email"), ("whatsapp", "whatsapp"), ("hypothesis", "hypothesis"), ("conversationResult", "conversation_result"), ("nextAction", "next_action"), ("status", "status")]:
        if incoming in d:
            setattr(a, attr, d.get(incoming))
    if "icpScore" in d:
        a.icp_score = max(0, min(100, int(d.get("icpScore") or 0)))
    if "nextActionAt" in d:
        a.next_action_at = datetime.fromisoformat(d["nextActionAt"]) if d.get("nextActionAt") else None
    db.session.commit()
    return jsonify(account=a.to_dict())


@hub_bp.post("/<market_code>/api/accounts/<int:account_id>/send-to-radar")
@require_permission("WRITE_CRM")
def send_to_radar(market_code, account_id):
    market = _market_or_404(market_code)
    a = _account_or_404(account_id, market_code)
    if not market["radarEnabled"]:
        return jsonify(error="O Radar Argentina ainda não está ativado. A conta permanecerá isolada no HUB Argentina."), 409
    t = current_tenant()
    company = resolve_company(t.id, a.company_name, website=a.website, country="Paraguay", email=a.email, whatsapp=a.whatsapp)
    a.company_id = company.id
    a.sent_to_radar_at = datetime.now(timezone.utc)
    a.status = "SENT_TO_RADAR"
    db.session.commit()
    return jsonify(companyId=company.id, account=a.to_dict())


@hub_bp.post("/<market_code>/api/events/<int:event_id>/results")
@require_permission("WRITE_CRM")
def save_results(market_code, event_id):
    row = _event_or_404(event_id, market_code)
    d = request.get_json(silent=True) or {}
    row.actual_results = d
    if d.get("close"):
        row.status = "CLOSED"
        row.closed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(event=row.to_dict())


@hub_bp.get("/<market_code>/api/sources")
def sources(market_code):
    if not _allowed():
        abort(404)
    market = _market_or_404(market_code)
    rows = HubEventSource.query.filter_by(tenant_id=current_tenant().id, market_code=market["code"]).order_by(HubEventSource.priority.asc(), HubEventSource.name.asc()).all()
    return jsonify(sources=[x.to_dict() for x in rows])


@hub_bp.post("/<market_code>/api/sources")
@require_permission("WRITE_CRM")
def add_source(market_code):
    market = _market_or_404(market_code)
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    name = (d.get("name") or "").strip()
    if not url or not name:
        return jsonify(error="Nome e URL obrigatórios"), 400
    row = HubEventSource.query.filter_by(tenant_id=current_tenant().id, market_code=market["code"], url=url).first()
    if not row:
        row = HubEventSource(tenant_id=current_tenant().id, market_code=market["code"], name=name, url=url, country=market["country"], priority=d.get("priority") or "B", source_type=d.get("sourceType") or "OFFICIAL")
        db.session.add(row)
    db.session.commit()
    return jsonify(source=row.to_dict())


@hub_bp.post("/<market_code>/api/sources/seed")
@require_permission("WRITE_CRM")
def seed_sources(market_code):
    market = _market_or_404(market_code)
    presets = {
        "PY": [
            ("MIC Paraguay", "https://www.mic.gov.py/", "A"),
            ("REDIEX", "https://www.rediex.gov.py/", "A"),
            ("UIP", "https://www.uip.org.py/", "A"),
            ("Fecomércio GO", "https://www.fecomerciogo.org.br/", "B"),
        ],
        "AR": [
            ("Argentina Producción", "https://www.argentina.gob.ar/produccion", "A"),
            ("Unión Industrial Argentina", "https://www.uia.org.ar/", "A"),
            ("ADIMRA", "https://www.adimra.org.ar/", "A"),
            ("Cámara Argentina de Comercio", "https://www.cac.com.ar/", "B"),
        ],
    }
    created = 0
    for name, url, priority in presets[market["code"]]:
        if not HubEventSource.query.filter_by(tenant_id=current_tenant().id, market_code=market["code"], url=url).first():
            db.session.add(HubEventSource(tenant_id=current_tenant().id, market_code=market["code"], name=name, url=url, country=market["country"], priority=priority))
            created += 1
    db.session.commit()
    return jsonify(created=created)


@hub_bp.post("/<market_code>/api/sources/scan")
@require_permission("RUN_COLLECTOR")
def scan_sources(market_code):
    market = _market_or_404(market_code)
    stats = run_hub_event_scan(current_tenant().id, market_code=market["code"])
    return jsonify(**stats)


@hub_bp.patch("/<market_code>/api/actions/<int:action_id>")
@require_permission("WRITE_CRM")
def action_update(market_code, action_id):
    market = _market_or_404(market_code)
    a = HubEventAction.query.filter_by(id=action_id, tenant_id=current_tenant().id, market_code=market["code"]).first_or_404()
    d = request.get_json(silent=True) or {}
    if d.get("status") in {"PENDING", "DONE", "CANCELLED"}:
        a.status = d["status"]
    db.session.commit()
    return jsonify(action=a.to_dict())
