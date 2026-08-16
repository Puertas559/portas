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
COLLECTOR_INTERVAL_MINUTES=60
COLLECTOR_MIN_SCORE=60
COLLECTOR_EXTRA_FEEDS=
AUTH_REQUIRED=true
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

La plataforma usa autenticación por sesión, aislamiento por tenant y roles `ADMIN`, `MANAGER`, `SALES` y `VIEWER`. `AUTH_REQUIRED=true` es el modo recomendado. Si no existe ningún usuario, el primer acceso redirige a `/setup` para crear el administrador general; después, nuevos usuarios se crean desde **Usuarios y accesos**. La aplicación genera y persiste una clave de sesión en `DATA_DIR` cuando `SECRET_KEY` no fue definida. La captación almacena evidencia empresarial pública y no realiza envíos comerciales automáticos.

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

## V7 · Ficha empresarial 360° e historial comercial

La V7 convierte cada empresa del CRM en una cuenta comercial completa. Desde **CRM → Ficha 360°** se puede consultar y editar razón social, RUC, sector, sedes, plantas, propietarios, actividades, contactos, proyectos, oportunidades, historial e información comercial.

### Cómo alimentar el historial

No es necesario escribir un informe después de cada paso. Use **Registrar interacción** para guardar en pocos segundos: llamada, correo enviado, WhatsApp, reunión, visita, propuesta, respuesta, seguimiento, nota o actualización de datos. La fecha/hora se guarda automáticamente. Cuando corresponda, registre resultado, resumen y próxima acción.

Registrar correo/WhatsApp/llamada mueve automáticamente una oportunidad nueva o calificada a **Contacto realizado**. Registrar una respuesta cambia a **Respondió**; una visita/reunión cambia a **Visita** y una propuesta enviada cambia a **Presupuesto**.

### Mensajes contextuales

La pestaña **Mensajes** de la ficha 360° genera una presentación institucional basada en la empresa y el destinatario. La redacción cambia cuando el contacto pertenece a Marketing/Comunicación, Compras, Mantenimiento/Ingeniería/Proyectos, Operaciones/Logística o Dirección. Si existe un nombre de contacto, se utiliza en la apertura. El modelo parte de la presentación institucional de Puertas Brasil y menciona carta de presentación y catálogo comercial.

### Datos que se completan manualmente

Los datos que no puedan inferirse con seguridad desde fuentes públicas —por ejemplo RUC, razón social exacta, propietarios, plantas de operación o información obtenida en una llamada— se completan en **Datos empresariales** dentro de la ficha 360°. Esto evita inventar información y mantiene trazabilidad comercial.

## V8 — Diagnóstico de sitios y presencia digital

- Los errores del calificador ahora explican causa, etapa, acción recomendada y detalles técnicos.
- Se distinguen URL inválida, DNS, timeout, bloqueo HTTP, SSL, 404, errores del servidor y fallos de conexión.
- El radar prueba variantes seguras del dominio y puede sugerir sitios alternativos verificados.
- El usuario puede analizar una alternativa, usarla como sitio principal o abrirla externamente.
- La Ficha 360° incorpora una pestaña de Presencia digital con sitio oficial, dominios alternativos, redes y fecha de verificación.

## V9 — Enriquecimiento automático de empresas

- Las empresas nuevas llevan datos estructurados del análisis web a la ficha 360° al ingresar al CRM.
- Las empresas existentes pueden actualizarse individualmente desde la ficha 360° o en lote desde **Completar CRM automáticamente**.
- El enriquecimiento completa únicamente campos vacíos por defecto y conserva las ediciones manuales existentes.
- Cada ejecución registra fuente, fecha, campos actualizados, campos preservados, confianza y datos que requieren revisión.
- Se detectan y consolidan presencia digital, sitio oficial, dominios alternativos y perfiles corporativos (LinkedIn, Facebook, Instagram y YouTube cuando están enlazados desde el sitio).
- El analizador intenta extraer razón social, RUC, año de fundación, propietarios/fundadores mencionados, plantas/unidades operativas, actividades, ubicación y canales de contacto. Los datos de menor confianza quedan marcados para revisión antes de usarlos comercialmente.


## V13 - administración, identidad y contacto inmediato
- Login corporativo Puertas Brasil PY con presentación visual y fotografías institucionales.
- Primer administrador mediante `/setup`; administración de usuarios, roles y activación/desactivación desde el panel.
- Al clasificar una empresa se abre la Ficha 360° en **Mensajes**.
- Cada correo descubierto se convierte en destinatario separado y se clasifica por área probable (Compras, Ventas, Mantenimiento, Operaciones, Gerencia, Marketing, etc.).
- Mensajes muestran el correo/teléfono exacto del destinatario y botones para copiar destinatario, asunto, mensaje o todo.
- Identificación de empresa prioriza datos estructurados y `og:site_name` antes del título de una página de contacto/historia.
- La Ficha 360° permite archivar empresas; el administrador también puede eliminarlas definitivamente.
- RUC y razón social extraídos del sitio cuando existe evidencia suficiente; la ficha enlaza la consulta oficial de DNIT para verificación.
