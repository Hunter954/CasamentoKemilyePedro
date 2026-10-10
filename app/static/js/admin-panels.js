document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => document.getElementById(button.dataset.openDialog)?.showModal());
  });
  document.querySelectorAll('.admin-dialog').forEach(dialog => {
    dialog.querySelector('[data-close-dialog]')?.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    }});
    if (dialog.hasAttribute('data-auto-open')) dialog.showModal();
  });
  const giftForm = document.querySelector('[data-gift-editor]');
  if (giftForm) {
    const title = giftForm.elements.title;
    const price = giftForm.elements.price;
    const update = () => {
      document.querySelector('[data-gift-preview-title]').textContent = title.value.trim() || 'Nome do presente';
      document.querySelector('[data-gift-preview-price]').textContent = new Intl.NumberFormat('pt-BR', {style:'currency', currency:'BRL'}).format(Number(price.value) || 0);
    };
    title.addEventListener('input', update);
    price.addEventListener('input', update);
    let objectURL;
    giftForm.querySelector('[data-gift-image]').addEventListener('change', event => {
      const file = event.target.files[0];
      if (objectURL) URL.revokeObjectURL(objectURL);
      if (!file) return;
      objectURL = URL.createObjectURL(file);
      const image = document.querySelector('[data-gift-preview-image]');
      image.src = objectURL;
      image.hidden = false;
    });
    update();
  }
  const message = document.querySelector('[data-message-editor]');
  if (message) {
    const update = () => {
      document.querySelector('[data-message-preview]').textContent = message.value
        .replaceAll('%contato%', 'Maria').replaceAll('%codigo%', '123456')
        .replaceAll('%nome_noivos%', 'Kemily & Pedro').replaceAll('%site_url%', window.location.origin);
    };
    message.addEventListener('input', update);
    document.querySelectorAll('[data-insert-token]').forEach(button => button.addEventListener('click', () => {
      const token = button.dataset.insertToken;
      message.setRangeText(token, message.selectionStart, message.selectionEnd, 'end');
      message.focus();
      update();
    }));
    update();
  }
  const board = document.querySelector('[data-progress-url]');
  if (board) {
    let polling = false;
    const poll = async () => {
      if (polling || document.hidden || document.querySelector('dialog[open]')) return;
      polling = true;
      try {
        const response = await fetch(board.dataset.progressUrl, {headers:{Accept:'application/json'}});
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
        const data = await response.json();
        for (const card of board.querySelectorAll('[data-campaign-id]')) {
          const queue = data[card.dataset.campaignId];
          if (!queue) continue;
          const previous = card.dataset.errorCount;
          const errors = queue.error + queue.uncertain;
          if (previous !== undefined && String(errors) !== previous) { window.location.reload(); return; }
          card.dataset.errorCount = String(errors);
          card.querySelector('.campaign-queue-progress').hidden = false;
          card.querySelector('[data-queue-summary]').textContent = `${queue.sent} / ${queue.total} mensagens enviadas`;
          card.querySelector('[data-queue-estimate]').textContent = `${queue.remaining} na fila · ~${queue.minutes} min`;
          card.querySelector('progress').value = queue.percent;
          card.querySelector('[data-queue-state]').textContent = queue.paused ? 'Pausada' : (queue.remaining ? 'Em andamento' : 'Concluída');
          card.querySelector('[data-queue-note]').textContent = errors ? 'Confira os erros no histórico antes de reenviar.' : (queue.paused ? 'Fila pausada. Retome quando desejar.' : 'Pode fechar esta página: os envios continuam em segundo plano.');
          const pause = card.querySelector('[data-pause-form]');
          pause.hidden = !queue.remaining;
          pause.elements.action.value = queue.paused ? 'resume' : 'pause';
          pause.querySelector('button').textContent = queue.paused ? 'Retomar fila' : 'Pausar fila';
        }
      } catch (_) { /* A later poll reconnects without interrupting the page. */ }
      finally { polling = false; }
    };
    setInterval(poll, 5000);
    poll();
  }
});
