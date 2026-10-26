document.addEventListener('DOMContentLoaded', () => {
  const normalize = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const collator = new Intl.Collator('pt-BR', {numeric:true, sensitivity:'base'});
  document.querySelectorAll('[data-filter-panel]').forEach(panel => {
    const list = panel.querySelector('[data-filter-list]');
    if (!list) return;
    const rows = Array.from(list.querySelectorAll('[data-filter-row]'));
    const search = panel.querySelector('[data-filter-search]');
    const sort = panel.querySelector('[data-filter-sort]');
    const from = panel.querySelector('[data-filter-from]');
    const to = panel.querySelector('[data-filter-to]');
    const selectors = Array.from(panel.querySelectorAll('[data-filter]'));
    const params = new URLSearchParams(location.search);
    if (params.has('status') && selectors.some(s => s.dataset.filter === 'status')) {
      const select = selectors.find(s => s.dataset.filter === 'status');
      if (Array.from(select.options).some(o => o.value === params.get('status'))) select.value = params.get('status');
    }
    const apply = () => {
      const query = normalize(search?.value.trim());
      const selected = selectors.map(s => [s.dataset.filter, s.value]);
      const invalidDates = from?.value && to?.value && from.value > to.value;
      const mode = sort?.value;
      const ordered = [...rows].sort((a,b) => {
        if (mode === 'az' || mode === 'za') return collator.compare(a.dataset.name,b.dataset.name) * (mode === 'za' ? -1 : 1);
        if (mode === 'high' || mode === 'low') return (Number(a.dataset.amount)-Number(b.dataset.amount)) * (mode === 'high' ? -1 : 1);
        if (mode === 'position') return rows.indexOf(a)-rows.indexOf(b);
        return collator.compare(a.dataset.date || '',b.dataset.date || '') * (mode === 'oldest' ? 1 : -1);
      });
      let count = 0, amount = 0;
      ordered.forEach(row => {
        const day = (row.dataset.date || '').slice(0,10);
        const statusMatch = selected.every(([key,value]) => !value || (key === 'status' && value === 'yes' ? ['yes','partial'].includes(row.dataset[key]) : normalize(row.dataset[key]) === normalize(value)));
        row.hidden = !!invalidDates || !statusMatch || (query && !normalize(row.dataset.search || row.textContent).includes(query)) || !!(from?.value && (!day || day < from.value)) || !!(to?.value && (!day || day > to.value));
        if (!row.hidden) { count++; amount += Number(row.dataset.amount || 0); }
        list.append(row);
      });
      const counter = panel.querySelector('[data-filter-count]');
      if (counter) counter.textContent = invalidDates ? 'A data final deve ser igual ou posterior à inicial.' : `${count} de ${rows.length} registros${panel.hasAttribute('data-filter-money') ? ' · '+new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(amount) : ''}`;
      panel.querySelector('[data-filter-empty]')?.toggleAttribute('hidden', count > 0);
    };
    panel.querySelectorAll('input,select').forEach(input => {
      if (input.closest('.ux-toolbar')) input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', apply);
    });
    panel.querySelector('[data-filter-clear]')?.addEventListener('click', () => {
      panel.querySelectorAll('.ux-toolbar input,.ux-toolbar select').forEach(input => { input.value = input === sort ? (sort.dataset.defaultSort || 'newest') : ''; });
      apply(); search?.focus();
    });
    panel.querySelector('[data-filter-export]')?.addEventListener('click', event => {
      const visible = Array.from(list.querySelectorAll('[data-filter-row]')).filter(row => !row.hidden);
      const safe = value => '"'+(/^[=+@\-\t\r]/.test(String(value)) ? "'" : '')+String(value).replace(/"/g,'""')+'"';
      const headers = JSON.parse(panel.dataset.csvHeaders || '[]');
      const values = visible.map(row => JSON.parse(row.dataset.csv || '[]'));
      const csv = '\ufeff'+[headers,...values].map(row => row.map(safe).join(';')).join('\r\n');
      const url = URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
      const link = document.createElement('a'); link.href = url; link.download = `${event.currentTarget.dataset.filterExport}-${new Date().toISOString().slice(0,10)}.csv`; link.click();
      setTimeout(() => URL.revokeObjectURL(url),1000);
    });
    apply();
  });
});
