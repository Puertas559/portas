(() => {
  'use strict';
  const root = document.documentElement;
  const body = document.body;
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  root.classList.toggle('pwa-standalone', isStandalone);

  // Service worker com escopo raiz. Não bloqueia a aplicação se falhar.
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch((err) => {
        console.warn('PWA service worker não registrado:', err);
      });
    });
  }

  // Estado de conexão, sem cache de dados comerciais.
  const syncOnlineState = () => body?.classList.toggle('pwa-offline', !navigator.onLine);
  window.addEventListener('online', syncOnlineState);
  window.addEventListener('offline', syncOnlineState);
  syncOnlineState();

  // Menu mobile retrátil para a interface operacional.
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
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
      if (window.innerWidth <= 760) closeNav();
    }));
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
