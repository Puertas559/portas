(() => {
  'use strict';
  const root = document.documentElement;
  const body = document.body;
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const mobileQuery = window.matchMedia('(max-width: 820px), (hover: none) and (pointer: coarse)');
  const isMobileUI = () => mobileQuery.matches || Math.min(screen.width || 9999, screen.height || 9999) <= 820;
  root.classList.toggle('pwa-touch-mobile', isMobileUI());
  root.classList.toggle('pwa-standalone', isStandalone);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch((err) => {
        console.warn('PWA service worker não registrado:', err);
      });
    });
  }

  const syncOnlineState = () => body?.classList.toggle('pwa-offline', !navigator.onLine);
  window.addEventListener('online', syncOnlineState);
  window.addEventListener('offline', syncOnlineState);
  syncOnlineState();
  const syncMobileUI = () => root.classList.toggle('pwa-touch-mobile', isMobileUI());
  window.addEventListener('resize', syncMobileUI, { passive: true });
  window.addEventListener('orientationchange', syncMobileUI);

  const sidebar = document.querySelector('.sidebar');
  let menuButton = null;
  const closeNav = () => body.classList.remove('pwa-nav-open');
  if (sidebar) {
    menuButton = document.createElement('button');
    menuButton.type = 'button';
    menuButton.className = 'pwa-mobile-menu';
    menuButton.setAttribute('aria-label', 'Abrir menu do Radar');
    menuButton.innerHTML = '<i class="bi bi-list"></i>';
    const backdrop = document.createElement('button');
    backdrop.type = 'button';
    backdrop.className = 'pwa-nav-backdrop';
    backdrop.setAttribute('aria-label', 'Fechar menu');
    document.body.append(menuButton, backdrop);
    menuButton.addEventListener('click', () => body.classList.toggle('pwa-nav-open'));
    backdrop.addEventListener('click', closeNav);
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
      if (isMobileUI()) closeNav();
    }));
  }

  // Navegação inferior existe somente na interface operacional (que possui sidebar).
  if (sidebar) {
  const bottomNav = document.createElement('nav');
  bottomNav.className = 'pwa-bottom-nav';
  bottomNav.setAttribute('aria-label', 'Navegação principal do Radar');
  const items = [
    { key: 'hoy', icon: 'bi-house-door', label: 'Hoje' },
    { key: 'crm', icon: 'bi-briefcase', label: 'CRM' },
    { key: 'search', icon: 'bi-search', label: 'Buscar' },
    { key: 'visitas', icon: 'bi-geo-alt', label: 'Visitas' },
    { key: 'more', icon: 'bi-grid', label: 'Mais' }
  ];
  bottomNav.innerHTML = items.map((item) => `<button type="button" data-pwa-action="${item.key}"><i class="bi ${item.icon}"></i><span>${item.label}</span></button>`).join('');
  document.body.appendChild(bottomNav);

  const navButton = (key) => bottomNav.querySelector(`[data-pwa-action="${key}"]`);
  const activateBottom = (key) => {
    bottomNav.querySelectorAll('button').forEach((button) => button.classList.toggle('active', button.dataset.pwaAction === key));
  };
  const openModule = (key) => {
    const link = document.querySelector(`.workflow-nav [data-module-target="${key}"]`);
    if (link) {
      link.click();
      activateBottom(key === 'hoy' || key === 'crm' || key === 'visitas' ? key : 'more');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  navButton('hoy')?.addEventListener('click', () => openModule('hoy'));
  navButton('crm')?.addEventListener('click', () => openModule('crm'));
  navButton('visitas')?.addEventListener('click', () => openModule('visitas'));
  navButton('more')?.addEventListener('click', () => {
    body.classList.remove('pwa-search-open');
    body.classList.add('pwa-nav-open');
  });
  navButton('search')?.addEventListener('click', () => {
    closeNav();
    body.classList.toggle('pwa-search-open');
    activateBottom('search');
    const input = document.getElementById('globalCompanySearch');
    if (body.classList.contains('pwa-search-open')) setTimeout(() => input?.focus(), 40);
  });
  document.addEventListener('click', (event) => {
    if (!isMobileUI() || !body.classList.contains('pwa-search-open')) return;
    if (event.target.closest('.global-company-search') || event.target.closest('[data-pwa-action="search"]')) return;
    body.classList.remove('pwa-search-open');
  });

  // Mantém o item inferior sincronizado quando o usuário navega pelo menu completo.
  document.querySelectorAll('.workflow-nav [data-module-target]').forEach((link) => {
    link.addEventListener('click', () => {
      const target = link.dataset.moduleTarget;
      if (['hoy', 'crm', 'visitas'].includes(target)) activateBottom(target);
      else activateBottom('more');
      body.classList.remove('pwa-search-open');
    });
  });
  activateBottom('hoy');
  }

  // Instalação no Android/Chrome/Edge. iOS usa Adicionar à Tela de Início.
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
