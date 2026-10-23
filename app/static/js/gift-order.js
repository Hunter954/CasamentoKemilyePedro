(() => {
  let saving = false;
  document.querySelectorAll('[data-gift-order]').forEach(editor => {
    const display = editor.querySelector('[data-order-display]');
    const edit = editor.querySelector('[data-order-edit]');
    const form = editor.querySelector('[data-order-form]');
    const input = editor.querySelector('[data-order-input]');
    const save = editor.querySelector('[data-order-save]');
    const cancel = editor.querySelector('[data-order-cancel]');
    const feedback = editor.querySelector('[data-order-feedback]');
    const close = () => {
      form.hidden = true;
      display.hidden = false;
      edit.focus({ preventScroll: true });
    };
    edit.addEventListener('click', () => {
      input.value = editor.dataset.position;
      feedback.textContent = '';
      feedback.classList.remove('is-error');
      display.hidden = true;
      form.hidden = false;
      input.focus({ preventScroll: true });
      input.select();
    });
    cancel.addEventListener('click', () => { if (!saving) { feedback.textContent = ''; close(); } });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !saving) { event.preventDefault(); cancel.click(); }
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (saving || !form.reportValidity()) return;
      const body = new FormData(form);
      saving = true;
      const buttons = Array.from(document.querySelectorAll('[data-gift-order] button'));
      buttons.forEach(button => { button.disabled = true; });
      input.disabled = true;
      form.setAttribute('aria-busy', 'true');
      save.textContent = 'Salvando…';
      feedback.textContent = '';
      feedback.classList.remove('is-error');
      let saved = false;
      try {
        const response = await fetch(form.getAttribute('action'), {
          method: 'POST', body, credentials: 'same-origin',
          headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(20000)
        });
        if (response.redirected || response.status === 400 || response.status === 401) {
          throw new Error('Atualize a página para entrar novamente e salvar.');
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.positions) throw new Error(data.error || 'Não foi possível salvar a ordem. Tente novamente.');
        document.querySelectorAll('[data-gift-id]').forEach(card => {
          const position = data.positions[card.dataset.giftId];
          const row = card.querySelector('[data-gift-order]');
          if (!row || !Number.isInteger(position)) return;
          row.dataset.position = position;
          row.querySelector('[data-order-value]').textContent = position;
          const rowForm = row.querySelector('[data-order-form]');
          if (rowForm.hidden) row.querySelector('[data-order-input]').value = position;
          row.querySelector('[data-order-input]').max = data.count;
        });
        feedback.textContent = 'Ordem salva. Os outros presentes foram ajustados.';
        saved = true;
      } catch (error) {
        feedback.classList.add('is-error');
        feedback.textContent = error.message || 'Não foi possível salvar. Tente novamente.';
      } finally {
        saving = false;
        buttons.forEach(button => { button.disabled = false; });
        input.disabled = false;
        form.removeAttribute('aria-busy');
        save.textContent = 'Salvar';
        if (saved) close();
      }
    });
  });
})();
