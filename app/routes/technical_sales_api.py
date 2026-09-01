from __future__ import annotations

import base64
import binascii
import html
import io
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    Company,
    CompanyActivity,
    TechnicalSurvey,
    TechnicalSurveyAttachment,
    TechnicalSurveyEvent,
)
from ..tenant import current_tenant, current_user, require_permission

technical_sales_api_bp = Blueprint("technical_sales_api", __name__, url_prefix="/api/technical-surveys")

STATUS_LABELS = {
    "DRAFT": "Rascunho",
    "PENDING_VALIDATION": "Aguardando validação técnica",
    "VALIDATED": "Validado",
    "QUOTE_GENERATED": "Orçamento gerado",
    "APPROVED": "Aprovado",
}

TRANSITIONS = {
    "DRAFT": {"PENDING_VALIDATION"},
    "PENDING_VALIDATION": {"DRAFT", "VALIDATED"},
    "VALIDATED": {"PENDING_VALIDATION", "QUOTE_GENERATED"},
    "QUOTE_GENERATED": {"VALIDATED", "APPROVED"},
    "APPROVED": {"QUOTE_GENERATED"},
}

REQUIRED_FIELDS = (
    "client_name", "phone", "address", "city_country", "work_type", "work_status", "sales_responsible",
    "width_top", "width_middle", "width_bottom", "height_left", "height_middle", "height_right", "finish_state",
    "headroom", "left_side", "right_side", "depth", "structure_material", "structure_condition",
    "panel_type", "color_finish", "operation_mode", "cycles_day", "usage_context", "usage_intensity",
    "voltage", "other_access", "power_available",
)

ALLOWED_MIMES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
MAX_ATTACHMENT_BYTES = 14 * 1024 * 1024


def _now():
    return datetime.now(timezone.utc)


def _current_role():
    user = current_user()
    return user.role if user else "ADMIN"


def _can_validate():
    return _current_role() in {"GROUP_ADMIN", "ADMIN", "MANAGER"}


def _missing_required(fields):
    fields = fields or {}
    return [key for key in REQUIRED_FIELDS if str(fields.get(key) or "").strip() == ""]


def _progress(fields):
    if not REQUIRED_FIELDS:
        return 100
    missing = _missing_required(fields)
    return round(((len(REQUIRED_FIELDS) - len(missing)) / len(REQUIRED_FIELDS)) * 100)


def _event(survey, action, summary, *, from_status=None, to_status=None, extra=None):
    user = current_user()
    db.session.add(TechnicalSurveyEvent(
        tenant_id=survey.tenant_id,
        survey_id=survey.id,
        user_id=user.id if user else None,
        action=action,
        from_status=from_status,
        to_status=to_status,
        summary=summary,
        extra_data=extra or {},
    ))


def _company_activity(survey, subject, summary, extra=None):
    if not survey.company_id:
        return
    user = current_user()
    db.session.add(CompanyActivity(
        tenant_id=survey.tenant_id,
        company_id=survey.company_id,
        activity_type="NOTE",
        channel="LEVANTAMENTO_TECNICO",
        direction="INTERNAL",
        subject=subject,
        summary=summary,
        occurred_at=_now(),
        created_by=user.name if user else "Equipe",
        extra_data={"technicalSurveyId": survey.id, "reference": survey.reference, **(extra or {})},
    ))


def _attachment_dict(row):
    return {
        "id": row.id,
        "group": row.group_key,
        "name": row.original_filename,
        "mimeType": row.mime_type,
        "size": row.size_bytes,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "url": f"/api/technical-surveys/attachments/{row.id}/file",
    }


def _event_dict(row):
    return {
        "id": row.id,
        "action": row.action,
        "fromStatus": row.from_status,
        "toStatus": row.to_status,
        "summary": row.summary,
        "extra": row.extra_data or {},
        "user": row.user.name if row.user else "Sistema",
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def _survey_dict(row, *, detail=False):
    data = {
        "id": row.id,
        "reference": row.reference,
        "status": row.status,
        "statusLabel": STATUS_LABELS.get(row.status, row.status),
        "companyId": row.company_id,
        "company": ({
            "id": row.company.id,
            "name": row.company.name,
            "city": row.company.city,
            "country": row.company.country,
        } if row.company else None),
        "clientName": (row.fields or {}).get("client_name"),
        "cityCountry": (row.fields or {}).get("city_country"),
        "budgetTotal": float(row.budget_total or 0),
        "progress": row.progress or 0,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "createdBy": row.created_by.name if row.created_by else None,
        "validatedBy": row.validated_by.name if row.validated_by else None,
        "submittedAt": row.submitted_at.isoformat() if row.submitted_at else None,
        "validatedAt": row.validated_at.isoformat() if row.validated_at else None,
        "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
        "signedAt": row.signed_at.isoformat() if row.signed_at else None,
        "signatureName": row.signature_name,
        "hasSignature": bool(row.signature_data),
    }
    if detail:
        data.update({
            "fields": row.fields or {},
            "budget": row.budget or {},
            "commercial": row.commercial or {},
            "validationNotes": row.validation_notes or "",
            "signatureData": row.signature_data,
            "missingRequired": _missing_required(row.fields or {}),
            "attachments": [_attachment_dict(x) for x in sorted(row.attachments, key=lambda a: a.created_at or _now())],
            "events": [_event_dict(x) for x in sorted(row.events, key=lambda e: e.created_at or _now(), reverse=True)],
            "permissions": {
                "canValidate": _can_validate(),
                "canEdit": row.status in {"DRAFT", "PENDING_VALIDATION"},
                "canDelete": row.status == "DRAFT",
            },
        })
    return data


def _survey_or_404(survey_id):
    tenant = current_tenant()
    return TechnicalSurvey.query.filter_by(id=survey_id, tenant_id=tenant.id).first_or_404()


def _attachment_root(survey):
    root = Path(current_app.config["DATA_DIR"]) / "technical-sales" / str(survey.tenant_id) / str(survey.id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_budget_total(value):
    try:
        return max(0, round(float(value or 0), 2))
    except (TypeError, ValueError):
        return 0


def _status_message(status):
    return STATUS_LABELS.get(status, status)


@technical_sales_api_bp.get("")
def list_surveys():
    tenant = current_tenant()
    query = TechnicalSurvey.query.filter_by(tenant_id=tenant.id)
    status = str(request.args.get("status") or "").strip().upper()
    if status in STATUS_LABELS:
        query = query.filter_by(status=status)
    rows = query.order_by(TechnicalSurvey.updated_at.desc()).limit(250).all()
    return jsonify(items=[_survey_dict(row) for row in rows], permissions={"canValidate": _can_validate()})


@technical_sales_api_bp.post("")
@require_permission("WRITE_CRM")
def create_survey():
    tenant = current_tenant()
    user = current_user()
    data = request.get_json(silent=True) or {}
    company = None
    if data.get("companyId"):
        company = Company.query.filter_by(id=data["companyId"], tenant_id=tenant.id, status="ACTIVE").first_or_404()
    fields = dict(data.get("fields") or {})
    if user and not fields.get("sales_responsible"):
        fields["sales_responsible"] = user.name
    row = TechnicalSurvey(
        tenant_id=tenant.id,
        company_id=company.id if company else None,
        reference=f"LEV-{_now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
        status="DRAFT",
        fields=fields,
        budget=dict(data.get("budget") or {}),
        commercial=dict(data.get("commercial") or {}),
        budget_total=_safe_budget_total(data.get("budgetTotal")),
        progress=_progress(fields),
        created_by_user_id=user.id if user else None,
        updated_by_user_id=user.id if user else None,
    )
    db.session.add(row)
    db.session.flush()
    _event(row, "CREATED", "Ficha técnico-comercial criada no servidor.")
    if company:
        _company_activity(row, "Levantamento técnico criado", f"A ficha {row.reference} foi vinculada à empresa {company.name}.")
    db.session.commit()
    return jsonify(_survey_dict(row, detail=True)), 201


@technical_sales_api_bp.get("/<int:survey_id>")
def get_survey(survey_id):
    return jsonify(_survey_dict(_survey_or_404(survey_id), detail=True))


@technical_sales_api_bp.patch("/<int:survey_id>")
@require_permission("WRITE_CRM")
def update_survey(survey_id):
    row = _survey_or_404(survey_id)
    user = current_user()
    data = request.get_json(silent=True) or {}
    technical_change = "fields" in data
    commercial_change = any(key in data for key in ("budget", "commercial", "budgetTotal"))
    if technical_change and row.status not in {"DRAFT", "PENDING_VALIDATION"}:
        return jsonify(error="As medidas e dados técnicos ficam bloqueados após a validação. Reabra a ficha para revisão técnica."), 409
    if commercial_change and row.status not in {"DRAFT", "PENDING_VALIDATION", "VALIDATED"}:
        return jsonify(error="A composição comercial fica bloqueada depois que o orçamento é gerado. Reabra o orçamento para editar valores."), 409

    company_changed = False
    old_company_id = row.company_id
    if "companyId" in data:
        company_id = data.get("companyId") or None
        company = None
        if company_id:
            company = Company.query.filter_by(id=company_id, tenant_id=row.tenant_id, status="ACTIVE").first_or_404()
            company_id = company.id
        if company_id != row.company_id:
            row.company_id = company_id
            company_changed = True

    if "fields" in data:
        row.fields = dict(data.get("fields") or {})
        row.progress = _progress(row.fields)
    if "budget" in data:
        row.budget = dict(data.get("budget") or {})
    if "commercial" in data:
        row.commercial = dict(data.get("commercial") or {})
    if "budgetTotal" in data:
        row.budget_total = _safe_budget_total(data.get("budgetTotal"))
    if "validationNotes" in data:
        row.validation_notes = str(data.get("validationNotes") or "").strip() or None
    row.updated_by_user_id = user.id if user else None

    if company_changed:
        _event(row, "CRM_LINK_CHANGED", "Vínculo da ficha com o CRM foi alterado.", extra={"fromCompanyId": old_company_id, "toCompanyId": row.company_id})
        if row.company_id:
            _company_activity(row, "Ficha técnica vinculada", f"A ficha {row.reference} foi vinculada a este cliente/empresa.")
    db.session.commit()
    return jsonify(_survey_dict(row, detail=True))


@technical_sales_api_bp.delete("/<int:survey_id>")
@require_permission("WRITE_CRM")
def delete_survey(survey_id):
    row = _survey_or_404(survey_id)
    if row.status != "DRAFT":
        return jsonify(error="Somente fichas em rascunho podem ser excluídas."), 409
    root = _attachment_root(row)
    db.session.delete(row)
    db.session.commit()
    try:
        for child in root.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        root.rmdir()
    except OSError:
        pass
    return jsonify(ok=True)


@technical_sales_api_bp.post("/<int:survey_id>/status")
@require_permission("WRITE_CRM")
def change_status(survey_id):
    row = _survey_or_404(survey_id)
    data = request.get_json(silent=True) or {}
    target = str(data.get("status") or "").strip().upper()
    if target not in STATUS_LABELS:
        return jsonify(error="Status inválido."), 400
    if target not in TRANSITIONS.get(row.status, set()):
        return jsonify(error=f"Transição não permitida: {_status_message(row.status)} → {_status_message(target)}."), 409
    if target == "PENDING_VALIDATION" and row.status == "DRAFT":
        missing = _missing_required(row.fields or {})
        if missing:
            return jsonify(error="Preencha os campos essenciais antes de enviar para validação.", missingRequired=missing), 422
    if target == "VALIDATED" and not _can_validate():
        return jsonify(error="A validação técnica exige perfil de gestor ou administrador."), 403
    if target == "APPROVED" and not row.signature_data:
        return jsonify(error="Registre a assinatura do cliente/responsável antes de marcar o orçamento como aprovado."), 422

    previous = row.status
    row.status = target
    user = current_user()
    row.updated_by_user_id = user.id if user else None
    notes = str(data.get("notes") or "").strip()
    if notes:
        row.validation_notes = notes
    now = _now()
    if target == "PENDING_VALIDATION":
        row.submitted_at = now
        if previous == "VALIDATED":
            row.validated_at = None
            row.validated_by_user_id = None
    elif target == "VALIDATED":
        row.validated_at = now
        row.validated_by_user_id = user.id if user else None
    elif target == "APPROVED":
        row.approved_at = now
    elif target == "QUOTE_GENERATED" and previous == "APPROVED":
        row.approved_at = None

    summary = f"Status alterado de {_status_message(previous)} para {_status_message(target)}."
    _event(row, "STATUS_CHANGED", summary, from_status=previous, to_status=target, extra={"notes": notes} if notes else None)
    _company_activity(row, "Atualização da ficha técnica", f"{row.reference}: {summary}", {"status": target})
    db.session.commit()
    return jsonify(_survey_dict(row, detail=True))


@technical_sales_api_bp.post("/<int:survey_id>/signature")
@require_permission("WRITE_CRM")
def save_signature(survey_id):
    row = _survey_or_404(survey_id)
    if row.status not in {"QUOTE_GENERATED", "APPROVED"}:
        return jsonify(error="A assinatura fica disponível após a geração do orçamento."), 409
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    signature = str(data.get("signatureData") or "").strip()
    if not name or not signature.startswith("data:image/png;base64,"):
        return jsonify(error="Informe o nome do assinante e registre a assinatura no quadro."), 422
    try:
        raw = base64.b64decode(signature.split(",", 1)[1], validate=True)
    except (ValueError, binascii.Error):
        return jsonify(error="Assinatura inválida."), 400
    if len(raw) > 750_000:
        return jsonify(error="Assinatura excede o tamanho permitido."), 413
    row.signature_name = name[:220]
    row.signature_data = signature
    row.signed_at = _now()
    user = current_user()
    row.updated_by_user_id = user.id if user else None
    _event(row, "SIGNED", f"Ficha assinada por {row.signature_name}.")
    _company_activity(row, "Assinatura registrada", f"A ficha {row.reference} recebeu assinatura de {row.signature_name}.")
    db.session.commit()
    return jsonify(_survey_dict(row, detail=True))


@technical_sales_api_bp.post("/<int:survey_id>/attachments")
@require_permission("WRITE_CRM")
def upload_attachments(survey_id):
    row = _survey_or_404(survey_id)
    if row.status not in {"DRAFT", "PENDING_VALIDATION"}:
        return jsonify(error="Os anexos ficam bloqueados após a validação técnica."), 409
    group = secure_filename(str(request.form.get("group") or "general"))[:80] or "general"
    files = request.files.getlist("file") or request.files.getlist("files")
    if not files:
        return jsonify(error="Nenhum arquivo recebido."), 400
    root = _attachment_root(row)
    user = current_user()
    created = []
    for file in files:
        if not file or not file.filename:
            continue
        mime = (file.mimetype or "").lower()
        if mime not in ALLOWED_MIMES:
            return jsonify(error=f"Formato não permitido: {file.filename}"), 415
        file.stream.seek(0, 2)
        size = file.stream.tell()
        file.stream.seek(0)
        if size <= 0 or size > MAX_ATTACHMENT_BYTES:
            return jsonify(error=f"Arquivo excede o limite permitido: {file.filename}"), 413
        original = secure_filename(file.filename) or f"anexo{ALLOWED_MIMES[mime]}"
        stored = f"{uuid4().hex}{ALLOWED_MIMES[mime]}"
        path = root / stored
        file.save(path)
        attachment = TechnicalSurveyAttachment(
            tenant_id=row.tenant_id,
            survey_id=row.id,
            group_key=group,
            original_filename=original[:300],
            stored_filename=stored,
            mime_type=mime,
            size_bytes=size,
            relative_path=str(path.relative_to(Path(current_app.config["DATA_DIR"]))),
            created_by_user_id=user.id if user else None,
        )
        db.session.add(attachment)
        db.session.flush()
        created.append(attachment)
    if created:
        _event(row, "ATTACHMENT_ADDED", f"{len(created)} anexo(s) adicionado(s) em {group}.", extra={"group": group, "attachmentIds": [x.id for x in created]})
    db.session.commit()
    return jsonify(items=[_attachment_dict(x) for x in created]), 201


@technical_sales_api_bp.get("/attachments/<int:attachment_id>/file")
def attachment_file(attachment_id):
    tenant = current_tenant()
    row = TechnicalSurveyAttachment.query.filter_by(id=attachment_id, tenant_id=tenant.id).first_or_404()
    path = Path(current_app.config["DATA_DIR"]) / row.relative_path
    if not path.is_file():
        return jsonify(error="Arquivo não encontrado."), 404
    return send_file(path, mimetype=row.mime_type, as_attachment=False, download_name=row.original_filename, conditional=True)


@technical_sales_api_bp.delete("/attachments/<int:attachment_id>")
@require_permission("WRITE_CRM")
def delete_attachment(attachment_id):
    tenant = current_tenant()
    row = TechnicalSurveyAttachment.query.filter_by(id=attachment_id, tenant_id=tenant.id).first_or_404()
    survey = row.survey
    if survey.status not in {"DRAFT", "PENDING_VALIDATION"}:
        return jsonify(error="Os anexos ficam bloqueados após a validação técnica."), 409
    path = Path(current_app.config["DATA_DIR"]) / row.relative_path
    name = row.original_filename
    group = row.group_key
    db.session.delete(row)
    _event(survey, "ATTACHMENT_REMOVED", f"Anexo removido: {name}.", extra={"group": group})
    db.session.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return jsonify(ok=True)


def _format_money(value, tenant):
    amount = float(value or 0)
    country_code = str((tenant.settings or {}).get("country_code") or "BR").upper()
    if country_code == "PY":
        return f"Gs. {amount:,.0f}".replace(",", ".")
    return "R$ " + f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pdf_text(value):
    return html.escape(str(value or "—"))


def _build_pdf(survey):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    tenant = current_tenant()
    brand = tenant.settings or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=14*mm, leftMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TSTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#17352b"), spaceAfter=4)
    subtitle = ParagraphStyle("TSSub", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#59645f"))
    h2 = ParagraphStyle("TSH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#17352b"), spaceBefore=7, spaceAfter=5)
    body = ParagraphStyle("TSBody", parent=styles["Normal"], fontName="Helvetica", fontSize=8.2, leading=10.5)
    small = ParagraphStyle("TSSmall", parent=body, fontSize=7.2, leading=9, textColor=colors.HexColor("#5b6560"))
    center = ParagraphStyle("TSCenter", parent=body, alignment=TA_CENTER)

    story = []
    logo_file = str(brand.get("logo_file") or "")
    logo_path = Path(current_app.root_path) / "static" / logo_file if logo_file else None
    header_left = [Paragraph("Ficha técnico-comercial - Porta Seccionada Residencial", title), Paragraph(f"{_pdf_text(brand.get('brand_name') or tenant.name)} | {_pdf_text(survey.reference)}", subtitle)]
    header_data = [[header_left, ""]]
    if logo_path and logo_path.is_file():
        try:
            header_data[0][1] = RLImage(str(logo_path), width=36*mm, height=16*mm, kind="proportional")
        except Exception:
            pass
    header = Table(header_data, colWidths=[130*mm, 45*mm])
    header.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (1,0), (1,0), "RIGHT"), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story.extend([header, Spacer(1, 2*mm)])

    status_line = f"Status: <b>{_pdf_text(STATUS_LABELS.get(survey.status, survey.status))}</b>"
    if survey.company:
        status_line += f" | CRM: <b>{_pdf_text(survey.company.name)}</b>"
    story.append(Paragraph(status_line, body))
    story.append(Spacer(1, 3*mm))

    fields = survey.fields or {}
    field_groups = [
        ("1. Cliente e obra", [("Cliente", "client_name"), ("Telefone / WhatsApp", "phone"), ("E-mail", "email"), ("Endereço", "address"), ("Cidade / país", "city_country"), ("Tipo de obra", "work_type"), ("Situação da residência", "work_status"), ("Responsável técnico-comercial", "sales_responsible")]),
        ("2. Medidas do vão", [("Largura superior", "width_top"), ("Largura central", "width_middle"), ("Largura inferior", "width_bottom"), ("Altura esquerda", "height_left"), ("Altura central", "height_middle"), ("Altura direita", "height_right"), ("Diagonal 1", "diagonal_1"), ("Diagonal 2", "diagonal_2"), ("Obra acabada", "finish_state")]),
        ("3. Espaços disponíveis", [("Verga", "headroom"), ("Ombreira esquerda", "left_side"), ("Ombreira direita", "right_side"), ("Profundidade", "depth"), ("Interferências superiores", "upper_interferences"), ("Interferências na profundidade", "depth_interferences")]),
        ("4. Estrutura e elevação", [("Material da estrutura", "structure_material"), ("Condição da estrutura", "structure_condition"), ("Reforço metálico", "metal_reinforcement"), ("Requadro", "frame_required"), ("Posição de instalação", "installation_position"), ("Sistema de elevação", "lift_type")]),
        ("5. Porta, uso e automação", [("Painel", "panel_type"), ("Cor / acabamento", "color_finish"), ("Acionamento", "operation_mode"), ("Ciclos/dia", "cycles_day"), ("Tipo de uso", "usage_context"), ("Intensidade", "usage_intensity"), ("Tensão", "voltage"), ("Outra entrada", "other_access")]),
        ("6. Condições e observações", [("Energia no local", "power_available"), ("Acesso", "site_access"), ("Área de montagem", "assembly_area"), ("Restrições", "time_restrictions"), ("Observações finais", "final_notes")]),
    ]
    unit_keys = {"width_top", "width_middle", "width_bottom", "height_left", "height_middle", "height_right", "diagonal_1", "diagonal_2", "headroom", "left_side", "right_side", "depth"}
    for heading, items in field_groups:
        rows = []
        for label, key in items:
            value = fields.get(key)
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                value = ", ".join(map(str, value))
            if key in unit_keys and value not in (None, ""):
                value = f"{value} mm"
            rows.append([Paragraph(f"<b>{_pdf_text(label)}</b>", small), Paragraph(_pdf_text(value), body)])
        if rows:
            story.append(Paragraph(heading, h2))
            table = Table(rows, colWidths=[58*mm, 117*mm], repeatRows=0)
            table.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f2f5f3")),
                ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d7ded9")),
                ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
                ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ]))
            story.append(table)

    widths = [float(fields.get(k) or 0) for k in ("width_top", "width_middle", "width_bottom") if str(fields.get(k) or "").strip()]
    heights = [float(fields.get(k) or 0) for k in ("height_left", "height_middle", "height_right") if str(fields.get(k) or "").strip()]
    if widths and heights:
        story.append(Paragraph("Referência automática", h2))
        story.append(Paragraph(f"Menor largura x menor altura: <b>{min(widths):.0f} x {min(heights):.0f} mm</b>. A medida do vão não é necessariamente a medida final de fabricação.", body))

    budget = survey.budget or {}
    budget_labels = {
        "door": "Porta / painéis", "automation": "Automação", "accessories": "Acessórios", "transport": "Transporte",
        "installation": "Instalação", "reinforcement": "Reforço estrutural", "electrical": "Elétrica / adicionais", "taxes": "Impostos / outros",
    }
    budget_rows = []
    for key, label in budget_labels.items():
        try:
            value = float(str(budget.get(key) or "0").replace(".", "").replace(",", "."))
        except ValueError:
            value = 0
        if value:
            budget_rows.append([Paragraph(_pdf_text(label), body), Paragraph(f"<b>{_pdf_text(_format_money(value, tenant))}</b>", body)])
    if budget_rows:
        story.append(Paragraph("7. Composição comercial preliminar", h2))
        budget_rows.append([Paragraph("<b>Total preliminar</b>", body), Paragraph(f"<b>{_pdf_text(_format_money(survey.budget_total, tenant))}</b>", body)])
        table = Table(budget_rows, colWidths=[120*mm, 55*mm])
        table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d7ded9")), ("ALIGN", (1,0), (1,-1), "RIGHT"), ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#edf6f1")), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
        story.append(table)

    commercial = survey.commercial or {}
    if any(commercial.values()):
        story.append(Paragraph("8. Condições comerciais", h2))
        rows = []
        for key, label in (("payment", "Pagamento"), ("manufacture", "Fabricação"), ("installation_deadline", "Instalação"), ("validity", "Validade"), ("warranty", "Garantia"), ("approver", "Responsável pela aprovação"), ("excluded", "Não incluído")):
            if commercial.get(key):
                rows.append([Paragraph(f"<b>{_pdf_text(label)}</b>", small), Paragraph(_pdf_text(commercial[key]), body)])
        if rows:
            table = Table(rows, colWidths=[58*mm, 117*mm])
            table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#d7ded9")), ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f2f5f3")), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
            story.append(table)

    if survey.validation_notes:
        story.append(Paragraph("Validação técnica", h2))
        validator = survey.validated_by.name if survey.validated_by else "Aguardando responsável"
        story.append(Paragraph(f"Responsável: <b>{_pdf_text(validator)}</b><br/>{_pdf_text(survey.validation_notes)}", body))

    image_attachments = [a for a in survey.attachments if a.mime_type in {"image/jpeg", "image/png"}][:12]
    if image_attachments:
        story.append(Paragraph("Registro fotográfico", h2))
        cells = []
        row_cells = []
        for attachment in image_attachments:
            path = Path(current_app.config["DATA_DIR"]) / attachment.relative_path
            if not path.is_file():
                continue
            try:
                img = RLImage(str(path), width=54*mm, height=36*mm, kind="proportional")
                block = KeepTogether([img, Paragraph(_pdf_text(attachment.original_filename), center)])
                row_cells.append(block)
                if len(row_cells) == 3:
                    cells.append(row_cells); row_cells = []
            except Exception:
                continue
        if row_cells:
            while len(row_cells) < 3:
                row_cells.append("")
            cells.append(row_cells)
        if cells:
            table = Table(cells, colWidths=[58*mm]*3)
            table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (0,0), (-1,-1), "CENTER"), ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
            story.append(table)

    if survey.signature_data:
        story.append(Paragraph("Assinatura do cliente / responsável", h2))
        try:
            raw = base64.b64decode(survey.signature_data.split(",", 1)[1])
            sig = RLImage(io.BytesIO(raw), width=70*mm, height=24*mm, kind="proportional")
            story.append(sig)
        except Exception:
            pass
        signed_date = survey.signed_at.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC") if survey.signed_at else ""
        story.append(Paragraph(f"<b>{_pdf_text(survey.signature_name)}</b> - {signed_date}", body))

    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("VALIDAÇÃO: este documento permite elaborar uma estimativa/orçamento preliminar. A medida do vão não é necessariamente a medida final de fabricação. A liberação para fabricação depende da validação técnica das medidas, estrutura, interferências, componentes e condições do local.", small))

    def footer(canvas, document):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(colors.HexColor("#d7ded9"))
        canvas.line(14*mm, 9*mm, width-14*mm, 9*mm)
        canvas.setFillColor(colors.HexColor("#66716c"))
        canvas.setFont("Helvetica", 7)
        footer_text = " | ".join(filter(None, [brand.get("sales_phone"), brand.get("sales_email"), brand.get("website")]))
        canvas.drawString(14*mm, 5.5*mm, footer_text[:115])
        canvas.drawRightString(width-14*mm, 5.5*mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer


@technical_sales_api_bp.get("/<int:survey_id>/pdf")
def survey_pdf(survey_id):
    row = _survey_or_404(survey_id)
    if row.status not in {"QUOTE_GENERATED", "APPROVED"}:
        return jsonify(error="Valide a ficha e gere o orçamento antes de emitir o PDF definitivo."), 409
    buffer = _build_pdf(row)
    filename = f"{row.reference}-orcamento-preliminar.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)


@technical_sales_api_bp.post("/<int:survey_id>/generate-quote")
@require_permission("WRITE_CRM")
def generate_quote(survey_id):
    row = _survey_or_404(survey_id)
    if row.status not in {"VALIDATED", "QUOTE_GENERATED", "APPROVED"}:
        return jsonify(error="A ficha precisa estar validada tecnicamente antes de gerar o orçamento."), 409
    if row.status == "VALIDATED":
        previous = row.status
        row.status = "QUOTE_GENERATED"
        _event(row, "QUOTE_GENERATED", "Orçamento preliminar gerado a partir da ficha validada.", from_status=previous, to_status=row.status)
        _company_activity(row, "Orçamento preliminar gerado", f"O orçamento da ficha {row.reference} foi gerado após validação técnica.")
        db.session.commit()
    return jsonify(ok=True, survey=_survey_dict(row, detail=True), pdfUrl=f"/api/technical-surveys/{row.id}/pdf")
