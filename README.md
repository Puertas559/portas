# Industrial Revenue Radar — Puertas Brasil PY

Radar de oportunidades comerciales de Puertas Brasil PY, desarrollado con Python Flask para Railway.

Esta es la primera implementación vertical de una plataforma genérica de Revenue Intelligence B2B. La evaluación, arquitectura objetivo, estrategia de migración y riesgos están documentados en [`docs/architecture-phase1.md`](docs/architecture-phase1.md).

## Arquitectura

- Flask 3 + Jinja + JavaScript
- PostgreSQL con SQLAlchemy
- Migraciones Alembic/Flask-Migrate
- Gunicorn en producción
- `/data` para archivos persistentes
- Captación automática mediante DNCP, MIC, agregadores y feeds configurables
- Ejecución automática cada 5 minutos con filtro de necesidad concreta
- Calificación de sitios empresariales con contactos, dirección, responsables, tamaño y afinidad comercial
- Docker y Railway

## Variables de Railway

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=genere-una-clave-larga-y-aleatoria
DATA_DIR=/data
RAILWAY_RUN_UID=0
WEB_CONCURRENCY=1
COLLECTOR_ENABLED=true
COLLECTOR_INTERVAL_MINUTES=5
COLLECTOR_MIN_SCORE=60
COLLECTOR_EXTRA_FEEDS=
AUTH_REQUIRED=false
ADMIN_EMAIL=
ADMIN_PASSWORD=
ADMIN_NAME=Administrador
DEFAULT_TENANT_NAME=Puertas Brasil PY
DEFAULT_TENANT_SLUG=puertas-brasil-py
SESSION_COOKIE_SECURE=true
```

`COLLECTOR_EXTRA_FEEDS` acepta URLs RSS/Atom separadas por comas. Permite agregar cámaras de comercio, asociaciones, parques industriales, ferias y medios especializados sin modificar el código.

## Persistencia

Conecte un volumen al servicio Flask en `/data`. PostgreSQL debe permanecer como servicio separado con su propia persistencia.

## Despliegue

1. Suba el contenido del paquete al repositorio.
2. Haga commit y push en la rama conectada a Railway.
3. Configure las variables indicadas.
4. Confirme el volumen en `/data`.
5. Use **Deploy Latest Commit**.

El contenedor ejecuta `flask db upgrade` y el bootstrap idempotente del tenant antes de iniciar Gunicorn.

## Rutas principales

- `/` — panel comercial y captación automática
- `/health` — estado de la base de datos
- `GET/POST /api/opportunities`
- `PATCH /api/opportunities/<id>`
- `GET /api/timeline/<id>`
- `GET /api/collector/status`
- `POST /api/collector/run`
- `POST /api/signals/<id>/approve`
- `POST /api/signals/<id>/discard`
- `GET/POST /api/website-analysis`
- `GET /api/companies`
- `GET /api/projects`
- `GET /api/sources`
- `GET /api/intelligence/signals`
- `GET /api/signals`
- `GET /api/scores`
- `GET /api/opportunities/<id>/intelligence`
- `GET /api/dashboard/revenue-intelligence`
- `POST /api/auth/login`

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app wsgi.py db upgrade
flask --app wsgi.py run --debug
```

Sin PostgreSQL local, la aplicación utiliza SQLite únicamente para desarrollo. En producción, `start.sh` exige `DATABASE_URL`.

## Seguridad

La plataforma dispone de autenticación por sesión, aislamiento por tenant y roles `ADMIN`, `MANAGER`, `SALES` y `VIEWER`. Para evitar bloquear el despliegue actual, active `AUTH_REQUIRED=true` solamente después de configurar `ADMIN_EMAIL`, `ADMIN_PASSWORD` y una `SECRET_KEY` fuerte. La captación almacena evidencia empresarial pública y no realiza envíos comerciales automáticos.

## Sales Workspace V5

A interface foi reorganizada para operar como ferramenta diária de vendas, não como uma página longa. O módulo inicial é o qualificador por site; cada item da navegação abre apenas o workspace correspondente.

Principais recursos V5:
- Qualificação individual e em lote (até 25 sites por execução).
- Research Queue com completude, dados faltantes, prioridade e validade dos dados.
- Lead Readiness Score e flag Sales Ready.
- Buying Committee com decisor, influenciadores e dados de contato.
- Cadência comercial D0/D1/D3/D7/D14.
- Registro estruturado de resultado comercial e motivo de perda.
- Smart Lists atualizadas a partir do estado do CRM.
- Ações em massa para cadência, monitoramento e qualificação.
- Métricas de cobertura de decisores, completude, resposta, win rate e pipeline.
- Google Maps/Places removido do produto; empresas encontradas manualmente podem ser qualificadas pelo site e levadas ao CRM.

## Sales Workspace V6 — Performance & Clarity (sem IA)

A V6 prioriza velocidade, leitura e execução comercial sem depender de APIs de IA.

### Qualificação em duas etapas
- **Quick Scan**: até 3 páginas essenciais, timeout reduzido e resposta inicial rápida.
- **Deep Scan**: até 18 páginas relevantes, executado depois da ficha inicial sem bloquear a interface.
- **Cache de 12 horas**: análises profundas recentes são reutilizadas automaticamente.
- **Lote paralelo**: até 4 Quick Scans simultâneos para listas de até 25 sites.

### Operação
- Barra de progresso, skeleton loading e estados de análise.
- Atalho `/` para voltar ao qualificador e focar o campo de site.
- `Esc` fecha a ficha lateral.
- Contas semelhantes calculadas localmente por setor, produto, tipo de projeto e região.
- Captador automático recomendado a cada 60 minutos para reduzir carga e ruído.

### Sem dependências pagas
Não há integração obrigatória com OpenAI, Google Maps ou serviços de IA. O scoring continua explicável e baseado em evidências, regras comerciais e dados do próprio radar.
