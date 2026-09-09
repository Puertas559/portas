(() => {
  'use strict';
  const root = document.documentElement;
  const body = document.body;
  if (!body) return;

  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  root.classList.toggle('pwa-standalone', isStandalone);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/', updateViaCache: 'none' })
        .then((registration) => registration.update())
        .catch((err) => console.warn('PWA service worker não registrado:', err));
    });
  }

  const syncOnlineState = () => body.classList.toggle('pwa-offline', !navigator.onLine);
  window.addEventListener('online', syncOnlineState);
  window.addEventListener('offline', syncOnlineState);
  syncOnlineState();

  const isPhone = () => window.matchMedia('(max-width: 767px)').matches;

  const sidebar = document.querySelector('.sidebar');
  let menuButton = null;
  let backdrop = null;
  const closeNav = () => body.classList.remove('pwa-nav-open');

  if (sidebar) {
    menuButton = document.createElement('button');
    menuButton.type = 'button';
    menuButton.className = 'pwa-mobile-menu';
    menuButton.setAttribute('aria-label', 'Abrir menu do Radar');
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.innerHTML = '<i class="bi bi-list"></i>';

    backdrop = document.createElement('button');
    backdrop.type = 'button';
    backdrop.className = 'pwa-nav-backdrop';
    backdrop.setAttribute('aria-label', 'Fechar menu');

    document.body.append(menuButton, backdrop);
    menuButton.addEventListener('click', () => {
      const willOpen = !body.classList.contains('pwa-nav-open');
      body.classList.toggle('pwa-nav-open', willOpen);
      menuButton.setAttribute('aria-expanded', String(willOpen));
    });
    backdrop.addEventListener('click', closeNav);
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeNav));
  }

  // Navegação inferior apenas na tela principal e apenas como atalho para módulos já existentes.
  if (document.querySelector('.workflow-nav')) {
    const lang = (body.dataset.language || document.documentElement.lang || '').toLowerCase();
    const portuguese = lang.startsWith('pt');
    const items = portuguese
      ? [
          ['hoy','bi-house-door','Hoje'],
          ['crm','bi-briefcase','CRM'],
          ['triage','bi-search','Qualificar'],
          ['visitas','bi-geo-alt','Visitas'],
          ['__menu__','bi-grid','Mais']
        ]
      : [
          ['hoy','bi-house-door','Mi día'],
          ['crm','bi-briefcase','CRM'],
          ['triage','bi-search','Calificar'],
          ['visitas','bi-geo-alt','Visitas'],
          ['__menu__','bi-grid','Más']
        ];

    const bottom = document.createElement('nav');
    bottom.className = 'pwa-bottom-nav';
    bottom.setAttribute('aria-label', portuguese ? 'Navegação mobile' : 'Navegación móvil');

    const setActive = (target) => {
      bottom.querySelectorAll('button').forEach((button) => {
        button.classList.toggle('active', button.dataset.target === target);
      });
    };

    items.forEach(([target, icon, label]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.target = target;
      button.innerHTML = `<i class="bi ${icon}"></i><span>${label}</span>`;
      button.addEventListener('click', () => {
        if (target === '__menu__') {
          body.classList.add('pwa-nav-open');
          menuButton?.setAttribute('aria-expanded', 'true');
          return;
        }
        const link = document.querySelector(`.workflow-nav [data-module-target="${target}"]`);
        if (link) link.click();
        setActive(target);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
      bottom.appendChild(button);
    });

    document.querySelectorAll('.workflow-nav [data-module-target]').forEach((link) => {
      link.addEventListener('click', () => setActive(link.dataset.moduleTarget || ''));
    });
    document.body.appendChild(bottom);
    setActive(document.querySelector('.workflow-nav [data-module-target].active')?.dataset.moduleTarget || 'triage');
  }

  // Teclado virtual: preserva o campo visível e esconde apenas a barra inferior enquanto o teclado ocupa a tela.
  if (window.visualViewport) {
    const viewport = window.visualViewport;
    const syncVisualViewport = () => {
      root.style.setProperty('--pwa-visual-height', `${Math.round(viewport.height)}px`);
      const keyboardOpen = isPhone() && viewport.height < window.innerHeight * 0.76;
      body.classList.toggle('pwa-keyboard-open', keyboardOpen);
    };
    viewport.addEventListener('resize', syncVisualViewport);
    viewport.addEventListener('scroll', syncVisualViewport);
    syncVisualViewport();
  }

  document.addEventListener('focusin', (event) => {
    if (!isPhone()) return;
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.matches('input,select,textarea')) return;
    window.setTimeout(() => target.scrollIntoView({ block: 'center', behavior: 'smooth' }), 180);
  });

  window.addEventListener('resize', () => {
    if (!isPhone()) {
      closeNav();
      menuButton?.setAttribute('aria-expanded', 'false');
      body.classList.remove('pwa-keyboard-open');
    }
  });

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
