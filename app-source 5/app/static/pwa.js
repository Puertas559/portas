(() => {
  'use strict';
  const root = document.documentElement;
  const body = document.body;
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  root.classList.toggle('pwa-standalone', isStandalone);

  const ua = navigator.userAgent || '';
  const touchDevice = navigator.maxTouchPoints > 0;
  const narrowPhysicalScreen = Math.min(screen.width || 9999, screen.height || 9999) <= 760;
  const isiPhoneLike = /iPhone|iPod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1 && narrowPhysicalScreen);
  const forceMobile = isiPhoneLike || (touchDevice && narrowPhysicalScreen);
  root.classList.toggle('pwa-force-mobile', forceMobile);

  // Reafirma o viewport correto em navegadores embutidos que podem abrir em modo desktop.
  if (forceMobile) {
    let viewport = document.querySelector('meta[name="viewport"]');
    if (!viewport) {
      viewport = document.createElement('meta');
      viewport.name = 'viewport';
      document.head.prepend(viewport);
    }
    viewport.setAttribute('content', 'width=device-width, initial-scale=1.0, viewport-fit=cover');
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
    menuButton.innerHTML = '<i class="bi bi-list"></i>';
    const backdrop = document.createElement('button');
    backdrop.type = 'button';
    backdrop.className = 'pwa-nav-backdrop';
    backdrop.setAttribute('aria-label', 'Fechar menu');
    document.body.append(menuButton, backdrop);
    const closeNav = () => body.classList.remove('pwa-nav-open');
    menuButton.addEventListener('click', () => body.classList.toggle('pwa-nav-open'));
    backdrop.addEventListener('click', closeNav);
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeNav));
  }

  // Navegação inferior no celular, sem duplicar módulos.
  if (document.querySelector('.workflow-nav')) {
    const bottom = document.createElement('nav');
    bottom.className = 'pwa-bottom-nav';
    bottom.setAttribute('aria-label', 'Navegação mobile');
    const items = [
      ['hoy','bi-house-door','Hoje'],
      ['crm','bi-briefcase','CRM'],
      ['triage','bi-search','Buscar'],
      ['visitas','bi-geo-alt','Visitas'],
      ['__menu__','bi-grid','Mais']
    ];
    items.forEach(([target, icon, label]) => {
      const b = document.createElement('button');
      b.type='button'; b.dataset.target=target;
      b.innerHTML=`<i class="bi ${icon}"></i><span>${label}</span>`;
      b.addEventListener('click', () => {
        if (target === '__menu__') { body.classList.add('pwa-nav-open'); return; }
        const link = document.querySelector(`.workflow-nav [data-module-target="${target}"]`);
        if (link) link.click();
        document.querySelectorAll('.pwa-bottom-nav button').forEach(x=>x.classList.toggle('active', x===b));
        window.scrollTo({top:0,behavior:'smooth'});
      });
      bottom.appendChild(b);
    });
    document.body.appendChild(bottom);
  }

  let deferredInstallPrompt = null;
  const installButton = document.createElement('button');
  installButton.type = 'button';
  installButton.className = 'pwa-install-button';
  installButton.innerHTML = '<i class="bi bi-phone"></i><span>Instalar app</span>';
  document.body.appendChild(installButton);
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault(); deferredInstallPrompt = event;
    if (!isStandalone) installButton.classList.add('is-visible');
  });
  installButton.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt(); await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null; installButton.classList.remove('is-visible');
  });
  window.addEventListener('appinstalled', () => { deferredInstallPrompt = null; installButton.classList.remove('is-visible'); });
})();
