(() => {
  let busy = false;
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-rsvp-form]');
    if (!form) return;
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const body = new FormData(form);
    if (event.submitter?.name) body.set(event.submitter.name, event.submitter.value);
    busy = true;
    const panel = document.querySelector('[data-rsvp-panel]');
    const buttons = Array.from(panel.querySelectorAll('button'));
    const feedback = form.querySelector('[data-rsvp-loading]');
    if (feedback) feedback.textContent = body.get('action') === 'lookup' ? 'Consultando seu convite…' : 'Salvando sua resposta…';
    buttons.forEach(button => { button.disabled = true; });
    panel.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(form.getAttribute('action') || window.location.pathname, {
        method: 'POST', body, credentials: 'same-origin',
        headers: { Accept: 'text/html' }, signal: AbortSignal.timeout(20000)
      });
      if (!response.ok) throw new Error();
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = doc.querySelector('[data-rsvp-panel]');
      if (!next) throw new Error();
      document.querySelector('.flash-wrap')?.remove();
      const notices = doc.querySelector('.flash-wrap');
      if (notices) document.body.prepend(notices);
      panel.replaceWith(next);
      next.querySelector('[data-rsvp-heading]')?.focus({ preventScroll: true });
    } catch (_) {
      if (feedback) feedback.textContent = 'Não foi possível consultar a resposta. Tente novamente ou atualize a página; uma resposta já salva será mantida.';
    } finally {
      busy = false;
      buttons.forEach(button => { button.disabled = false; });
      panel.removeAttribute('aria-busy');
    }
  });
})();
