(() => {
  'use strict';
  const root = document.documentElement;
  const body = document.body;
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  root.classList.toggle('pwa-standalone', isStandalone);

  const RADAR_BUILD = '20260909-smart-capture-v1.5-qr-fast';
  try { localStorage.setItem('radar_build', RADAR_BUILD); } catch (_) {}
  if ('caches' in window) {
    caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('hg-radar-') || k.startsWith('hg-radar-industrial-')).map(k => caches.delete(k)))).catch(()=>{});
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/', updateViaCache: 'none' })
        .then((registration) => registration.update())
        .catch((err) => console.warn('PWA service worker não registrado:', err));
    });
  }

  const syncOnlineState = () => body?.classList.toggle('pwa-offline', !navigator.onLine);
  window.addEventListener('online', syncOnlineState);
  window.addEventListener('offline', syncOnlineState);
  syncOnlineState();

  const sidebar = document.querySelector('.sidebar');
  if (sidebar) {
    const menuButton = document.createElement('button');
    menuButton.type = 'button';
    menuButton.className = 'pwa-mobile-menu';
    menuButton.setAttribute('aria-label', 'Abrir menu do Radar');
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.innerHTML = '<i class="bi bi-list"></i>';
    const backdrop = document.createElement('button');
    backdrop.type = 'button';
    backdrop.className = 'pwa-nav-backdrop';
    backdrop.setAttribute('aria-label', 'Fechar menu');
    document.body.append(menuButton, backdrop);
    const setNav = (open) => {
      body.classList.toggle('pwa-nav-open', open);
      menuButton.setAttribute('aria-expanded', String(open));
      menuButton.innerHTML = open ? '<i class="bi bi-x-lg"></i>' : '<i class="bi bi-list"></i>';
    };
    menuButton.addEventListener('click', () => setNav(!body.classList.contains('pwa-nav-open')));
    backdrop.addEventListener('click', () => setNav(false));
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setNav(false)));
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setNav(false); });
  }

  if (document.querySelector('.workflow-nav')) {
    const language = document.body.dataset.language || 'es-PY';
    const pt = language === 'pt-BR';
    const bottom = document.createElement('nav');
    bottom.className = 'pwa-bottom-nav';
    bottom.setAttribute('aria-label', pt ? 'Navegação mobile' : 'Navegación móvil');
    const items = [
      ['hoy','bi-house-door',pt ? 'Hoje' : 'Hoy'],
      ['crm','bi-briefcase','CRM'],
      ['triage','bi-search',pt ? 'Buscar' : 'Buscar'],
      ['visitas','bi-geo-alt',pt ? 'Visitas' : 'Visitas'],
      ['__menu__','bi-grid',pt ? 'Mais' : 'Más']
    ];
    const markActive = (target) => bottom.querySelectorAll('button').forEach((x) => x.classList.toggle('active', x.dataset.target === target));
    items.forEach(([target, icon, label]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.target = target;
      button.innerHTML = `<i class="bi ${icon}"></i><span>${label}</span>`;
      button.addEventListener('click', () => {
        if (target === '__menu__') { body.classList.add('pwa-nav-open'); return; }
        const link = document.querySelector(`.workflow-nav [data-module-target="${target}"]`);
        if (link) link.click();
        markActive(target);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
      bottom.appendChild(button);
    });
    document.body.appendChild(bottom);
    markActive('triage');
    document.querySelectorAll('.workflow-nav [data-module-target]').forEach((link) => link.addEventListener('click', () => {
      if (link.dataset.moduleTarget) markActive(link.dataset.moduleTarget);
    }));
  }

  let deferredInstallPrompt = null;
  const installButton = document.createElement('button');
  installButton.type = 'button';
  installButton.className = 'pwa-install-button';
  installButton.innerHTML = '<i class="bi bi-phone"></i><span>Instalar app</span>';
  document.body.appendChild(installButton);
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    if (!isStandalone) installButton.classList.add('is-visible');
  });
  installButton.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    installButton.classList.remove('is-visible');
  });
  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    installButton.classList.remove('is-visible');
  });
})();
