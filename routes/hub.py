from datetime import date, datetime, timezone
from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from ..extensions import db
from ..models import HubEvent, HubEventAccount, HubEventAction, HubEventSource, Tenant
from ..services.entity_resolution import normalize_domain, normalize_name, resolve_company
from ..services.hub_events import (
    apply_automatic_intelligence, build_playbook, create_detected_event,
    event_key, extract_page, run_hub_event_scan
)
from ..tenant import current_tenant, current_user, require_permission

hub_bp = Blueprint('hub', __name__, url_prefix='/hub')


def _allowed():
    tenant = current_tenant()
    return tenant.slug == 'puertas-brasil-py'


def _event_or_404(event_id):
    tenant=current_tenant(); return HubEvent.query.filter_by(id=event_id, tenant_id=tenant.id).first_or_404()




@hub_bp.get('/enter')
def enter():
    user = current_user()
    if not user:
        abort(403)
    if user.role == 'GROUP_ADMIN':
        tenant = Tenant.query.filter_by(slug='puertas-brasil-py', status='ACTIVE').first_or_404()
        session['active_tenant_id'] = tenant.id
        return redirect(url_for('hub.home'))
    if user.tenant and user.tenant.slug == 'puertas-brasil-py':
        return redirect(url_for('hub.home'))
    abort(403)


@hub_bp.get('/health')
def health():
    if not _allowed():
        abort(404)
    try:
        tenant = current_tenant()
        return jsonify(
            ok=True,
            module='hub-events',
            tenant=tenant.slug,
            events=HubEvent.query.filter_by(tenant_id=tenant.id).count(),
            sources=HubEventSource.query.filter_by(tenant_id=tenant.id).count(),
            message='HUB Eventos ativo e tabelas acessíveis',
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify(ok=False, module='hub-events', error=str(exc)), 500


@hub_bp.get('/')
def home():
    if not _allowed(): abort(404)
    return render_template('hub/index.html', tenant=current_tenant(), brand=current_tenant().settings or {}, user=current_user())


@hub_bp.get('/api/overview')
def overview():
    if not _allowed(): abort(404)
    t=current_tenant(); rows=HubEvent.query.filter_by(tenant_id=t.id).order_by(HubEvent.start_date.asc().nullslast(), HubEvent.created_at.desc()).all()
    active=[x for x in rows if x.status in {'APPROVED','PREPARATION','EXECUTION','FOLLOW_UP'}]
    return jsonify(events=[x.to_dict() for x in rows], metrics={
        'detected': sum(x.status in {'DETECTED','TRIAGE'} for x in rows), 'active': len(active),
        'approved': sum(x.status in {'APPROVED','PREPARATION','EXECUTION','FOLLOW_UP','CLOSED'} for x in rows),
        'pipelinePotential': sum(float((x.projection or {}).get('pipelinePotential') or 0) for x in active),
        'investment': sum(float(x.cost_estimate or 0) for x in active),
    })


@hub_bp.post('/api/events')
@require_permission('WRITE_CRM')
def create_event():
    if not _allowed(): abort(404)
    d=request.get_json(silent=True) or {}; name=(d.get('name') or '').strip()
    if not name: return jsonify(error='Nombre obligatorio'),400
    sd=date.fromisoformat(d['startDate']) if d.get('startDate') else None
    row,created=create_detected_event(current_tenant().id,name,url=d.get('url'),source_mode='MANUAL',start_date=sd,city=d.get('city'),organizer=d.get('organizer'),country=d.get('country') or 'Paraguay',event_type=d.get('eventType'),description=d.get('description'),confidence=90)
    if created:
        row.start_date=sd; row.city=d.get('city'); row.organizer=d.get('organizer'); row.event_type=d.get('eventType'); row.description=d.get('description'); row.normalized_key=event_key(row.name,row.start_date,row.city,row.organizer)
    db.session.commit(); return jsonify(event=row.to_dict(), created=created),201 if created else 200


@hub_bp.post('/api/events/import-url')
@require_permission('WRITE_CRM')
def import_url():
    if not _allowed(): abort(404)
    d=request.get_json(silent=True) or {}; url=(d.get('url') or '').strip()
    if not url: return jsonify(error='URL obligatoria'),400
    try: info=extract_page(url)
    except Exception as exc: return jsonify(error=f'No fue posible leer la página: {exc}'),422
    row,created=create_detected_event(
        current_tenant().id, info['name'], url=url, source_mode='URL',
        start_date=info.get('startDate'), city=info.get('city'), organizer=info.get('organizer'),
        country=info.get('country') or 'Paraguay', event_type=info.get('eventType'),
        description=info.get('description'), confidence=70
    )
    apply_automatic_intelligence(row, info, create_accounts=True)
    db.session.commit(); return jsonify(event=row.to_dict(include_children=True),created=created)


@hub_bp.get('/api/events/<int:event_id>')
def event_detail(event_id):
    if not _allowed(): abort(404)
    return jsonify(event=_event_or_404(event_id).to_dict(include_children=True))


@hub_bp.patch('/api/events/<int:event_id>')
@require_permission('WRITE_CRM')
def update_event(event_id):
    if not _allowed(): abort(404)
    row=_event_or_404(event_id); d=request.get_json(silent=True) or {}
    for incoming,attr in [('name','name'),('city','city'),('country','country'),('organizer','organizer'),('url','url'),('eventType','event_type'),('description','description'),('participationMode','participation_mode'),('notes','notes'),('currency','currency')]:
        if incoming in d: setattr(row,attr,d.get(incoming))
    if 'startDate' in d: row.start_date=date.fromisoformat(d['startDate']) if d.get('startDate') else None
    if 'endDate' in d: row.end_date=date.fromisoformat(d['endDate']) if d.get('endDate') else None
    if 'costEstimate' in d: row.cost_estimate=max(0,float(d.get('costEstimate') or 0))
    if 'status' in d:
        allowed={'DETECTED','TRIAGE','VALIDATED','ANALYSIS','APPROVED','PREPARATION','EXECUTION','FOLLOW_UP','CLOSED','MONITOR','DISCARDED'}
        if d['status'] not in allowed: return jsonify(error='Estado inválido'),400
        row.status=d['status']
        if row.status=='APPROVED': row.approved_at=datetime.now(timezone.utc); build_playbook(row,current_user().name if current_user() else 'Equipe HUB')
        if row.status=='CLOSED': row.closed_at=datetime.now(timezone.utc)
    row.normalized_key=event_key(row.name,row.start_date,row.city,row.organizer)
    db.session.commit(); return jsonify(event=row.to_dict(include_children=True))


@hub_bp.post('/api/events/<int:event_id>/reanalyze')
@require_permission('WRITE_CRM')
def reanalyze_event(event_id):
    if not _allowed(): abort(404)
    row=_event_or_404(event_id)
    if not row.url: return jsonify(error='Este evento no tiene URL para reanálisis automático.'),400
    try: info=extract_page(row.url)
    except Exception as exc: return jsonify(error=f'No fue posible reanalizar la página: {exc}'),422
    apply_automatic_intelligence(row, info, create_accounts=True)
    if row.status in {'DETECTED','TRIAGE'}: row.status='ANALYSIS'
    db.session.commit()
    return jsonify(event=row.to_dict(include_children=True))


@hub_bp.post('/api/events/<int:event_id>/score')
@require_permission('WRITE_CRM')
def score_event(event_id):
    row=_event_or_404(event_id); d=request.get_json(silent=True) or {}
    # pesos: comercial 70, econômico 20, estratégico 10
    commercial=sum(max(0,min(100,int(d.get(k,0))))*w for k,w in {'icp':.25,'timing':.20,'decisionAccess':.15,'preAccess':.10}.items())
    economic=max(0,min(100,int(d.get('economicEfficiency',0))))
    strategic=(max(0,min(100,int(d.get('partnership',0))))*.5 + max(0,min(100,int(d.get('visibility',0))))*.5)
    row.commercial_score=round(commercial/0.70); row.economic_score=round(economic); row.strategic_score=round(strategic)
    row.total_score=round(commercial + economic*.20 + strategic*.10)
    previous=row.score_details or {}
    row.score_details={**d,'automatic':False,'evidence':previous.get('evidence') or {},'analyzedAt':previous.get('analyzedAt'),'validatedAt':datetime.now(timezone.utc).isoformat(),'validatedBy':current_user().name if current_user() else None}
    row.status='ANALYSIS' if row.status in {'DETECTED','TRIAGE','VALIDATED'} else row.status
    db.session.commit(); return jsonify(event=row.to_dict())


@hub_bp.post('/api/events/<int:event_id>/projection')
@require_permission('WRITE_CRM')
def projection(event_id):
    row=_event_or_404(event_id); d=request.get_json(silent=True) or {}
    relevant=max(0,int(d.get('relevantAccounts') or 0)); meetings=max(0,int(d.get('meetings') or 0)); visits=max(0,int(d.get('visits') or 0)); opps=max(0,int(d.get('opportunities') or 0)); ticket=max(0,float(d.get('averageTicket') or 0)); probability=max(0,min(100,float(d.get('probability') or 20)))
    raw=opps*ticket; weighted=raw*(probability/100); cost=float(row.cost_estimate or 0)
    row.projection={'relevantAccounts':relevant,'meetings':meetings,'visits':visits,'opportunities':opps,'averageTicket':ticket,'probability':probability,'pipelinePotential':raw,'weightedPipeline':weighted,'pipelineCostMultiple':round(raw/cost,1) if cost else None}
    db.session.commit(); return jsonify(event=row.to_dict())


@hub_bp.post('/api/events/<int:event_id>/accounts')
@require_permission('WRITE_CRM')
def add_account(event_id):
    row=_event_or_404(event_id); d=request.get_json(silent=True) or {}; name=(d.get('companyName') or '').strip()
    if not name:return jsonify(error='Empresa obligatoria'),400
    existing=HubEventAccount.query.filter_by(tenant_id=row.tenant_id,event_id=row.id,company_name=name).first()
    if existing:return jsonify(account=existing.to_dict(),duplicate=True)
    a=HubEventAccount(tenant_id=row.tenant_id,event_id=row.id,company_name=name,website=d.get('website'),role=d.get('role') or 'PARTICIPANT',tier=d.get('tier') or 'C',icp_score=max(0,min(100,int(d.get('icpScore') or 0))),contact_name=d.get('contactName'),contact_role=d.get('contactRole'),email=d.get('email'),whatsapp=d.get('whatsapp'),hypothesis=d.get('hypothesis'))
    # vínculo somente se empresa já existir; não cria CRM nesta etapa
    domain=normalize_domain(a.website)
    from ..models import Company
    q=Company.query.filter_by(tenant_id=row.tenant_id,status='ACTIVE')
    company=q.filter_by(domain=domain).first() if domain else q.filter_by(normalized_name=normalize_name(name)).first()
    a.company_id=company.id if company else None
    db.session.add(a);db.session.commit();return jsonify(account=a.to_dict()),201


@hub_bp.patch('/api/accounts/<int:account_id>')
@require_permission('WRITE_CRM')
def update_account(account_id):
    t=current_tenant(); a=HubEventAccount.query.filter_by(id=account_id,tenant_id=t.id).first_or_404();d=request.get_json(silent=True) or {}
    for incoming,attr in [('tier','tier'),('role','role'),('contactName','contact_name'),('contactRole','contact_role'),('email','email'),('whatsapp','whatsapp'),('hypothesis','hypothesis'),('conversationResult','conversation_result'),('nextAction','next_action'),('status','status')]:
        if incoming in d:setattr(a,attr,d.get(incoming))
    if 'icpScore' in d:a.icp_score=max(0,min(100,int(d.get('icpScore') or 0)))
    if 'nextActionAt' in d:a.next_action_at=datetime.fromisoformat(d['nextActionAt']) if d.get('nextActionAt') else None
    db.session.commit();return jsonify(account=a.to_dict())


@hub_bp.post('/api/accounts/<int:account_id>/send-to-radar')
@require_permission('WRITE_CRM')
def send_to_radar(account_id):
    t=current_tenant(); a=HubEventAccount.query.filter_by(id=account_id,tenant_id=t.id).first_or_404()
    company=resolve_company(t.id,a.company_name,website=a.website,country=t.settings.get('default_country','Paraguay'),email=a.email,whatsapp=a.whatsapp)
    a.company_id=company.id;a.sent_to_radar_at=datetime.now(timezone.utc);a.status='SENT_TO_RADAR'
    db.session.commit();return jsonify(companyId=company.id,account=a.to_dict())


@hub_bp.post('/api/events/<int:event_id>/results')
@require_permission('WRITE_CRM')
def save_results(event_id):
    row=_event_or_404(event_id);d=request.get_json(silent=True) or {}; row.actual_results=d
    if d.get('close'): row.status='CLOSED';row.closed_at=datetime.now(timezone.utc)
    db.session.commit();return jsonify(event=row.to_dict())


@hub_bp.get('/api/sources')
def sources():
    if not _allowed():abort(404)
    return jsonify(sources=[x.to_dict() for x in HubEventSource.query.filter_by(tenant_id=current_tenant().id).order_by(HubEventSource.priority.asc(),HubEventSource.name.asc()).all()])


@hub_bp.post('/api/sources')
@require_permission('WRITE_CRM')
def add_source():
    if not _allowed():abort(404)
    d=request.get_json(silent=True) or {};url=(d.get('url') or '').strip();name=(d.get('name') or '').strip()
    if not url or not name:return jsonify(error='Nombre y URL obligatorios'),400
    row=HubEventSource.query.filter_by(tenant_id=current_tenant().id,url=url).first()
    if not row: row=HubEventSource(tenant_id=current_tenant().id,name=name,url=url,country=d.get('country'),priority=d.get('priority') or 'B',source_type=d.get('sourceType') or 'OFFICIAL');db.session.add(row)
    db.session.commit();return jsonify(source=row.to_dict())


@hub_bp.post('/api/sources/seed')
@require_permission('WRITE_CRM')
def seed_sources():
    if not _allowed():abort(404)
    presets=[('MIC Paraguay','https://www.mic.gov.py/','Paraguay','A'),('REDIEX','https://www.rediex.gov.py/','Paraguay','A'),('UIP','https://www.uip.org.py/','Paraguay','A'),('Fecomércio GO','https://www.fecomerciogo.org.br/','Brasil','B')]
    created=0
    for name,url,country,priority in presets:
        if not HubEventSource.query.filter_by(tenant_id=current_tenant().id,url=url).first():db.session.add(HubEventSource(tenant_id=current_tenant().id,name=name,url=url,country=country,priority=priority));created+=1
    db.session.commit();return jsonify(created=created)


@hub_bp.post('/api/sources/scan')
@require_permission('RUN_COLLECTOR')
def scan_sources():
    if not _allowed():abort(404)
    stats=run_hub_event_scan(current_tenant().id)
    return jsonify(**stats)


@hub_bp.patch('/api/actions/<int:action_id>')
@require_permission('WRITE_CRM')
def action_update(action_id):
    a=HubEventAction.query.filter_by(id=action_id,tenant_id=current_tenant().id).first_or_404();d=request.get_json(silent=True) or {}
    if d.get('status') in {'PENDING','DONE','CANCELLED'}:a.status=d['status']
    db.session.commit();return jsonify(action=a.to_dict())
