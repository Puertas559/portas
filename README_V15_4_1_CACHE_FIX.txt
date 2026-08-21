V15.4.1 — CACHE FIX

Causa identificada:
Os arquivos V15.4 estavam corretamente no projeto, mas index.html ainda usava query strings antigas (v13/v14/v15.3), permitindo que navegador/CDN reutilizasse JS/CSS antigos em cache.

Alteração:
Todos os assets principais recebem versão 20260821-v15.4.1 para forçar recarregamento dos arquivos atuais.

Substituir:
app/templates/index.html
