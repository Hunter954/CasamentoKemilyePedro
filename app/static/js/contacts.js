(() => {
  'use strict';
  const page = document.querySelector('[data-contacts-page]');
  if (!page) return;
  const find = selector => page.querySelector(selector);
  const initial = JSON.parse(document.getElementById('contacts-initial-data').textContent);
  let lastEvent = initial.latest;
  let polling = false;
  const initialTotal = initial.total;
  const status = find('[data-import-status]');
  const connection = find('[data-import-connection]');
  const history = find('[data-import-history]');
  const labels = { created: 'Cadastrado', duplicate: 'Já cadastrado', invalid: 'Nome ou telefone inválido' };
  const dateFormat = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

  function renderHistory(events) {
    history.replaceChildren();
    find('[data-import-history-count]').textContent = events.length;
    if (!events.length) {
      const empty = document.createElement('p');
      empty.className = 'contacts-history-help';
      empty.textContent = 'Os próximos contatos compartilhados no grupo aparecerão aqui.';
      history.append(empty);
    }
    for (const event of events) {
      const article = document.createElement('article');
      article.className = 'contacts-history-item';
      const title = document.createElement('strong');
      title.textContent = `${event.sender} · ${dateFormat.format(new Date(event.at))}`;
      const result = document.createElement('p');
      result.textContent = `${event.created} cadastrados · ${event.duplicates} já cadastrados · ${event.invalid} inválidos`;
      const group = document.createElement('p');
      group.textContent = event.group;
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'Ver contatos recebidos';
      const list = document.createElement('ul');
      for (const item of event.details) {
        const entry = document.createElement('li');
        entry.className = item.status === 'invalid' ? 'is-invalid' : '';
        entry.textContent = `${item.name} · ${labels[item.status] || item.status}`;
        list.append(entry);
      }
      details.append(summary, list);
      article.append(title, result, group, details);
      history.append(article);
    }
  }

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(25000) });
    if (response.redirected) throw new Error('A sessão expirou. Atualizem a página para entrar novamente.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Não foi possível atualizar. Tentem novamente.');
    return data;
  }

  async function poll() {
    if (polling || document.hidden) return;
    polling = true;
    try {
      const data = await getJson(page.dataset.statusUrl);
      find('[data-contact-total]').textContent = data.total;
      find('[data-import-created]').textContent = data.created;
      find('[data-import-duplicates]').textContent = data.duplicates;
      if (data.latest !== lastEvent) {
        renderHistory(data.events);
        lastEvent = data.latest;
      }
      find('[data-refresh-list]').hidden = data.total === initialTotal;
      status.classList.toggle('is-active', Boolean(data.enabled && data.bridge.ready));
      if (!data.enabled) {
        status.textContent = data.group_name ? 'Pausado' : 'Não ativado';
        connection.textContent = 'Ativem a importação para receber novos contatos do grupo escolhido.';
      } else if (data.bridge.ready) {
        status.textContent = 'Importação ativa';
        connection.textContent = data.bridge.pending > 0
          ? `${data.bridge.pending} lote(s) na fila. O sistema está processando e tentará novamente se necessário.`
          : 'WhatsApp conectado. Pronto para receber os próximos contatos do grupo.';
      } else {
        status.textContent = 'Aguardando conexão';
        connection.textContent = data.bridge.unavailable
          ? 'O serviço do WhatsApp está indisponível. Os lotes já recebidos ficam guardados para tentar novamente.'
          : 'O WhatsApp está desconectado. Confiram a conexão para receber novos contatos.';
      }
    } catch (error) {
      status.textContent = 'Atualização indisponível';
      status.classList.remove('is-active');
      connection.textContent = error.message;
    } finally { polling = false; }
  }

  const load = find('[data-load-groups]');
  const select = find('[data-group-select]');
  const save = find('[data-save-group]');
  const feedback = find('[data-group-feedback]');
  load.addEventListener('click', async () => {
    load.disabled = true;
    load.textContent = 'Buscando grupos…';
    select.disabled = true;
    save.disabled = true;
    feedback.classList.remove('is-error');
    feedback.textContent = '';
    try {
      const data = await getJson(page.dataset.groupsUrl);
      select.replaceChildren(new Option('Escolham o grupo de convidados', ''));
      for (const group of data.groups) {
        const option = new Option(`${group.name} · ${group.participants} participantes`, group.id);
        option.selected = group.id === select.dataset.currentGroup;
        select.append(option);
      }
      select.disabled = !data.groups.length;
      save.disabled = !select.value;
      feedback.textContent = data.groups.length
        ? 'Somente os contatos compartilhados no grupo selecionado serão cadastrados. Escolham um grupo reservado para isso.'
        : 'Nenhum grupo encontrado. Criem o grupo, adicionem o número conectado e busquem novamente.';
    } catch (error) {
      feedback.classList.add('is-error');
      feedback.textContent = error.message;
    } finally {
      load.disabled = false;
      load.textContent = 'Buscar meus grupos';
    }
  });
  select.addEventListener('change', () => { save.disabled = !select.value; });
  find('[data-open-contact-form]').addEventListener('click', () => {
    const form = document.getElementById('contact-form');
    form.open = true;
    form.querySelector('[name="name"]').focus({ preventScroll: true });
  });
  page.addEventListener('click', async event => {
    const button = event.target.closest('[data-copy-code]');
    if (!button) return;
    const copyFeedback = find('[data-copy-feedback]');
    try {
      await navigator.clipboard.writeText(button.dataset.copyCode);
      copyFeedback.textContent = `Código ${button.dataset.copyCode} copiado.`;
    } catch {
      const range = document.createRange();
      range.selectNodeContents(button.querySelector('code'));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      copyFeedback.textContent = 'O código está selecionado. Usem a opção Copiar do aparelho.';
    }
  });
  renderHistory(initial.events);
  poll();
  setInterval(poll, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
})();
