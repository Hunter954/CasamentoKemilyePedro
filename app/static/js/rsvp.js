(() => {
  let busy = false;
  function updateSelection(panel) {
    const choices = panel.querySelectorAll('[name="attendee"]');
    const selected = panel.querySelectorAll('[name="attendee"]:checked').length;
    const total = panel.querySelector('[data-selection-total]');
    if (total) total.textContent = `${selected} de ${choices.length} ${selected === 1 ? 'pessoa selecionada' : 'pessoas selecionadas'}`;
  }
  function startGiftTransition(panel) {
    if (!panel?.hasAttribute('data-gift-transition')) return;
    panel.removeAttribute('data-gift-transition');
    const overlay = panel.querySelector('[data-gift-handoff]');
    if (!overlay) return;
    let openTimer, redirectTimer, countdownTimer;
    const previousOverflow = document.body.style.overflow;
    const cancel = () => {
      clearTimeout(openTimer); clearTimeout(redirectTimer); clearInterval(countdownTimer);
      overlay.hidden = true;
      document.body.style.overflow = previousOverflow;
      overlay.removeEventListener('keydown', onKey);
      panel.querySelector('[data-rsvp-heading]')?.focus({ preventScroll: true });
    };
    const onKey = event => {
      if (event.key === 'Escape') cancel();
      if (event.key === 'Tab') {
        const items = overlay.querySelectorAll('a, button');
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement.id === 'gift-handoff-title')) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus();
        }
      }
    };
    overlay.querySelector('[data-cancel-gift-transition]').addEventListener('click', cancel, { once: true });
    openTimer = setTimeout(() => {
      if (!panel.isConnected) return;
      overlay.hidden = false;
      document.body.style.overflow = 'hidden';
      overlay.addEventListener('keydown', onKey);
      overlay.querySelector('h2').focus({ preventScroll: true });
      const deadline = Date.now() + 4800;
      const update = () => {
        overlay.querySelector('[data-gift-countdown]').textContent = `Abrindo a lista em ${Math.max(1, Math.ceil((deadline - Date.now()) / 1000))} segundos…`;
      };
      update(); countdownTimer = setInterval(update, 1000);
      redirectTimer = setTimeout(() => {
        clearInterval(countdownTimer);
        window.location.assign(overlay.dataset.giftsUrl);
      }, 4800);
    }, 1800);
  }
  document.addEventListener('change', event => {
    if (event.target.matches('[name="attendee"]')) updateSelection(event.target.closest('[data-rsvp-panel]'));
  });
  startGiftTransition(document.querySelector('[data-rsvp-panel]'));
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-rsvp-form]');
    if (!form) return;
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const body = new FormData(form);
    if (event.submitter?.name) body.set(event.submitter.name, event.submitter.value);
    const feedback = form.querySelector('[data-rsvp-loading]');
    if (body.get('attendance') === 'yes' && body.get('selection_present') === '1' && !body.getAll('attendee').length) {
      if (feedback) feedback.textContent = 'Selecione quem vai comparecer ou escolha “Não poderemos comparecer”.';
      return;
    }
    busy = true;
    const panel = document.querySelector('[data-rsvp-panel]');
    const buttons = Array.from(panel.querySelectorAll('button'));
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
      startGiftTransition(next);
    } catch (_) {
      if (feedback) feedback.textContent = 'Não foi possível consultar a resposta. Tente novamente ou atualize a página; uma resposta já salva será mantida.';
    } finally {
      busy = false;
      buttons.forEach(button => { button.disabled = false; });
      panel.removeAttribute('aria-busy');
    }
  });
})();
