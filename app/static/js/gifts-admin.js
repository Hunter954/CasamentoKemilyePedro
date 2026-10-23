(() => {
  const root = document.querySelector('[data-gift-dashboard]');
  if (!root) return;
  const list = root.querySelector('[data-gift-list]');
  const rows = [...list.querySelectorAll('[data-gift-id]')];
  const fields = Object.fromEntries(['search', 'status', 'type', 'price', 'sort'].map(key => [key, root.querySelector(`[data-gift-${key}]`)]));
  const defaults = {search: '', status: 'all', type: 'all', price: 'all', sort: 'position'};
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const storageKey = 'kemily-gift-catalog-filters';
  try {
    const stored = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    Object.entries(fields).forEach(([key, field]) => {
      if (typeof stored[key] === 'string') field.value = stored[key];
      if (!field.value && key !== 'search') field.value = defaults[key];
    });
  } catch (_) { /* Filters remain usable when browser storage is unavailable. */ }
  function applyFilters() {
    const state = Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.value]));
    const query = normalize(state.search);
    let count = 0;
    rows.forEach(row => {
      const d = row.dataset, price = Number(d.price);
      const status = state.status === 'all' || (state.status === 'active' && d.active === 'true') || (state.status === 'inactive' && d.active === 'false') || (state.status === 'soldout' && d.active === 'true' && d.soldout === 'true');
      const type = state.type === 'all' || d.multiple === String(state.type === 'multiple');
      const value = state.price === 'all' || (state.price === '100' && price <= 100) || (state.price === '300' && price > 100 && price <= 300) || (state.price === 'above' && price > 300);
      row.hidden = !(normalize(d.name).includes(query) && status && type && value);
      if (!row.hidden) count++;
      row.querySelectorAll('details[open]').forEach(menu => { menu.open = false; });
    });
    const sorted = [...rows].sort((a, b) => {
      if (state.sort === 'name') return a.dataset.name.localeCompare(b.dataset.name, 'pt-BR');
      if (state.sort === 'asc' || state.sort === 'desc') return (Number(a.dataset.price) - Number(b.dataset.price)) * (state.sort === 'asc' ? 1 : -1) || Number(a.dataset.sitePosition) - Number(b.dataset.sitePosition);
      return Number(a.dataset.sitePosition) - Number(b.dataset.sitePosition);
    });
    sorted.forEach(row => list.append(row));
    root.querySelector('[data-gift-result-count]').textContent = `${count} de ${rows.length} ${rows.length === 1 ? 'presente' : 'presentes'}`;
    root.querySelector('[data-gift-empty]').hidden = count > 0 || rows.length === 0;
    root.querySelector('[data-clear-gift-filters]').hidden = !Object.keys(defaults).some(key => state[key] !== defaults[key]);
    try { sessionStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) { /* Optional persistence. */ }
  }
  Object.entries(fields).forEach(([key, field]) => field.addEventListener(key === 'search' ? 'input' : 'change', applyFilters));
  root.querySelectorAll('[data-clear-gift-filters], [data-reset-gift-filters]').forEach(button => button.addEventListener('click', () => {
    Object.entries(fields).forEach(([key, field]) => { field.value = defaults[key]; });
    applyFilters(); fields.search.focus({preventScroll: true});
  }));
  applyFilters();
  let toastTimer;
  document.addEventListener('gift-order:saved', () => {
    const mode = root.querySelector('[data-order-mode]');
    mode.textContent = 'Ordem manual';
    const toast = root.querySelector('[data-gift-toast]');
    toast.textContent = 'Ordem salva! As posições no site foram atualizadas.';
    toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
  });
  document.addEventListener('click', event => {
    root.querySelectorAll('.gift-more[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  root.querySelectorAll('.gift-row-image img').forEach(img => {
    img.addEventListener('error', () => { img.hidden = true; });
    if (img.complete && !img.naturalWidth) img.hidden = true;
  });
  const dialog = root.querySelector('#gift-dialog');
  const form = dialog.querySelector('[data-gift-editor]');
  const preview = dialog.querySelector('[data-gift-preview-image]');
  let opener;
  function openEditor(button, row) {
    opener = button;
    const d = row ? row.dataset : null;
    form.reset();
    form.action = d ? d.editUrl : root.dataset.createUrl;
    form.elements.title.value = d ? d.name : '';
    form.elements.price.value = d ? d.price : '';
    form.elements.description.value = d ? d.description : '';
    form.elements.active.checked = !d || d.active === 'true';
    form.elements.allow_multiple_purchases.checked = !d || d.multiple === 'true';
    form.elements.image.value = '';
    dialog.querySelector('#gift-dialog-title').textContent = d ? 'Editar presente' : 'Novo presente';
    dialog.querySelector('[data-gift-submit]').textContent = d ? 'Salvar alterações' : 'Cadastrar presente';
    dialog.querySelector('.gift-editor-description').open = !!(d && d.description);
    preview.hidden = !(d && d.imageUrl);
    if (d && d.imageUrl) preview.src = d.imageUrl; else preview.removeAttribute('src');
    form.elements.title.dispatchEvent(new Event('input'));
    form.elements.price.dispatchEvent(new Event('input'));
    if (!dialog.open) dialog.showModal();
    form.elements.title.focus({preventScroll: true});
  }
  root.querySelectorAll('[data-edit-gift]').forEach(button => button.addEventListener('click', event => {event.preventDefault(); openEditor(button, button.closest('[data-gift-id]'));}));
  root.querySelectorAll('[data-new-gift]').forEach(button => button.addEventListener('click', () => openEditor(button, null)));
  dialog.querySelector('[data-gift-dialog-cancel]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { if (opener) opener.focus({preventScroll: true}); });
  preview.addEventListener('error', () => { preview.hidden = true; });
  form.elements.image.addEventListener('change', () => { if (form.elements.image.files.length) preview.hidden = false; });
  form.addEventListener('submit', () => {
    const submit = dialog.querySelector('[data-gift-submit]');
    submit.disabled = true; submit.textContent = 'Salvando…';
  });
})();
