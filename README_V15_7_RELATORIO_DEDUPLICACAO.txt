HG GRUPO · RADAR COMERCIAL — V15.7

Correções desta versão:
1. Empresas analisadas passam a ser contadas por identidade única, não por quantidade de WebsiteAnalysis.
2. Reanalisar o mesmo site não aumenta artificialmente o número de empresas.
3. A decisão classificada/descartada usa a análise mais recente de cada empresa.
4. Tarefas/seguimientos ficam separadas das métricas de empresas.
5. O relatório executivo mostra uma linha consolidada por empresa, não cada DATA_UPDATE/SITIO_WEB.
6. PDF e CSV passam a exportar empresas consolidadas e seu estado comercial.
7. Empresas contactadas, respostas, visitas, propostas e ganhos são KPIs por empresa única.
8. No deploy, bootstrap-tenant executa consolidação conservadora de duplicados existentes.
9. A consolidação automática usa somente RUC/registro, domínio ou nome normalizado exato; não usa fuzzy matching.
10. Contatos, atividades, projetos, sinais, watchlist e aliases são preservados ao consolidar.

Arquivos alterados:
- app/routes/api.py
- app/tenant.py
- app/services/data_quality.py
- app/templates/index.html
- app/static/workspace.js
- app/static/v13.css

Não exige migration.
