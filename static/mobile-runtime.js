(() => {
  'use strict';

  const root = document.documentElement;
  const body = document.body;
  const phoneQuery = window.matchMedia('(max-width: 767px)');
  const tabletQuery = window.matchMedia('(min-width: 768px) and (max-width: 1023px)');

  function updateDeviceClass() {
    root.classList.toggle('is-phone', phoneQuery.matches);
    root.classList.toggle('is-tablet', tabletQuery.matches);
  }

  function updateViewport() {
    const vv = window.visualViewport;
    const height = Math.round(vv?.height || window.innerHeight || document.documentElement.clientHeight);
    const top = Math.round(vv?.offsetTop || 0);
    root.style.setProperty('--app-height', `${height}px`);
    root.style.setProperty('--visual-offset-top', `${top}px`);

    const keyboardDelta = vv ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0;
    const keyboardOpen = phoneQuery.matches && keyboardDelta > 120;
    root.style.setProperty('--keyboard-inset', `${keyboardDelta}px`);
    root.classList.toggle('mobile-keyboard-open', keyboardOpen);
    body?.classList.toggle('mobile-keyboard-open', keyboardOpen);
  }

  function keepFocusedControlVisible(event) {
    if (!phoneQuery.matches) return;
    const el = event.target;
    if (!(el instanceof HTMLElement) || !el.matches('input,select,textarea,[contenteditable="true"]')) return;
    window.setTimeout(() => {
      try { el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' }); }
      catch (_) { el.scrollIntoView(); }
    }, 280);
  }

  updateDeviceClass();
  updateViewport();
  phoneQuery.addEventListener?.('change', () => { updateDeviceClass(); updateViewport(); });
  tabletQuery.addEventListener?.('change', updateDeviceClass);
  window.addEventListener('resize', updateViewport, { passive: true });
  window.addEventListener('orientationchange', () => window.setTimeout(updateViewport, 150), { passive: true });
  window.visualViewport?.addEventListener('resize', updateViewport, { passive: true });
  window.visualViewport?.addEventListener('scroll', updateViewport, { passive: true });
  document.addEventListener('focusin', keepFocusedControlVisible);
})();
