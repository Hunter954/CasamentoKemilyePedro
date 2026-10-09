document.addEventListener('DOMContentLoaded', () => {
  const countdown = document.querySelector('[data-countdown]');
  if (countdown) {
    const rawTarget = countdown.getAttribute('data-countdown') || '';
    const target = new Date(rawTarget);
    const hasValidTarget = !Number.isNaN(target.getTime());
    const els = {
      days: countdown.querySelector('[data-days]'),
      hours: countdown.querySelector('[data-hours]'),
      minutes: countdown.querySelector('[data-minutes]'),
      seconds: countdown.querySelector('[data-seconds]'),
    };

    const renderValues = (days, hours, minutes, seconds) => {
      if (els.days) els.days.textContent = String(days).padStart(2, '0');
      if (els.hours) els.hours.textContent = String(hours).padStart(2, '0');
      if (els.minutes) els.minutes.textContent = String(minutes).padStart(2, '0');
      if (els.seconds) els.seconds.textContent = String(seconds).padStart(2, '0');
    };

    if (hasValidTarget) {
      const update = () => {
        const now = new Date();
        const diff = Math.max(0, target - now);
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));
        const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
        const minutes = Math.floor((diff / (1000 * 60)) % 60);
        const seconds = Math.floor((diff / 1000) % 60);
        renderValues(days, hours, minutes, seconds);
      };
      update();
      setInterval(update, 1000);
    } else {
      renderValues(0, 0, 0, 0);
    }
  }


  const generateBtn = document.getElementById('generate-message-btn');
  const messageArea = document.getElementById('gift-message');
  if (generateBtn && messageArea) {
    generateBtn.addEventListener('click', async () => {
      const res = await fetch('/gerar-mensagem');
      const data = await res.json();
      messageArea.value = data.message;
    });
  }

  const giftSort = document.getElementById('kp-gift-sort');
  const giftGrid = document.getElementById('kp-gift-grid');
  if (giftGrid) {
    const cards = Array.from(giftGrid.querySelectorAll('.kp-gift-card'));
    const search = document.getElementById('kp-gift-search');
    const budget = document.getElementById('kp-gift-budget');
    const count = document.getElementById('kp-gift-count');
    const empty = document.getElementById('kp-gift-no-results');
    const normalize = (value) => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').trim();

    const updateGifts = () => {
      const query = normalize(search?.value);
      const maxPrice = !budget || budget.value === 'all' ? Infinity : Number(budget.value);
      const order = giftSort?.value || 'default';
      const sorted = [...cards].sort((a, b) => order === 'name'
        ? a.dataset.name.localeCompare(b.dataset.name, 'pt-BR')
        : order === 'desc'
          ? Number(b.dataset.price) - Number(a.dataset.price)
          : Number(a.dataset.price) - Number(b.dataset.price));
      let visible = 0;
      sorted.forEach((card) => {
        card.hidden = !normalize(card.dataset.name).includes(query) || Number(card.dataset.price) > maxPrice;
        if (!card.hidden) visible += 1;
        giftGrid.appendChild(card);
      });
      if (count) count.textContent = visible + (visible === 1 ? ' presente' : ' presentes') + (visible !== cards.length ? ' de ' + cards.length : '');
      if (empty) empty.hidden = cards.length === 0 || visible > 0;
    };

    search?.addEventListener('input', updateGifts);
    budget?.addEventListener('change', updateGifts);
    giftSort?.addEventListener('change', updateGifts);
    document.getElementById('kp-gift-reset')?.addEventListener('click', () => {
      if (search) search.value = '';
      if (budget) budget.value = 'all';
      if (giftSort) giftSort.value = 'default';
      updateGifts();
      search?.focus();
    });

    giftGrid.querySelectorAll('.kp-gift-photo img').forEach((img) => {
      const showFallback = () => {
        img.hidden = true;
        const fallback = img.parentElement.querySelector('.kp-gift-photo-fallback');
        if (fallback) fallback.hidden = false;
      };
      img.addEventListener('error', showFallback, { once: true });
      if (img.complete && img.naturalWidth === 0) showFallback();
    });
    updateGifts();
  }

  const body = document.body;
  const drawer = document.getElementById('site-drawer');
  const backdrop = document.querySelector('.drawer-backdrop');
  const openButton = document.querySelector('[data-menu-toggle]');
  const closeButtons = document.querySelectorAll('[data-menu-close]');

  const closeMenu = () => {
    if (!drawer) return;
    drawer.classList.remove('is-open');
    backdrop?.classList.remove('is-open');
    body.classList.remove('menu-open');
    if (openButton) openButton.setAttribute('aria-expanded', 'false');
    drawer.setAttribute('aria-hidden', 'true');
  };

  const openMenu = () => {
    if (!drawer) return;
    drawer.classList.add('is-open');
    backdrop?.classList.add('is-open');
    body.classList.add('menu-open');
    if (openButton) openButton.setAttribute('aria-expanded', 'true');
    drawer.setAttribute('aria-hidden', 'false');
  };

  openButton?.addEventListener('click', () => {
    if (drawer?.classList.contains('is-open')) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  closeButtons.forEach((button) => {
    button.addEventListener('click', closeMenu);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });

  const maskedPhoneInputs = document.querySelectorAll('input[data-phone-mask], input[name="buyer_phone"]');
  const zapiPhoneInputs = document.querySelectorAll('input[data-zapi-phone]');
  const formatPhone = (value) => {
    const digits = String(value || '').replace(/\D/g, '').slice(0, 11);
    if (!digits) return '';
    if (digits.length <= 2) return `(${digits}`;
    if (digits.length <= 6) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
    if (digits.length <= 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
    return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
  };

  maskedPhoneInputs.forEach((input) => {
    input.addEventListener('input', () => {
      input.value = formatPhone(input.value);
    });
    input.value = formatPhone(input.value);
  });

  zapiPhoneInputs.forEach((input) => {
    const sanitizeDigits = () => {
      input.value = String(input.value || '').replace(/\D/g, '').slice(0, 13);
    };

    input.addEventListener('input', sanitizeDigits);
    input.addEventListener('paste', () => {
      requestAnimationFrame(sanitizeDigits);
    });
    sanitizeDigits();
  });

  const homeHeader = document.querySelector('.kp-header-home');
  if (homeHeader) {
    const syncHeader = () => {
      homeHeader.classList.toggle('is-scrolled', window.scrollY > 24);
    };
    syncHeader();
    window.addEventListener('scroll', syncHeader, { passive: true });
  }

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const parallaxItems = reduceMotion ? [] : [...document.querySelectorAll('[data-parallax]')];

  if (parallaxItems.length) {
    let ticking = false;

    const updateParallax = () => {
      const scrolled = window.scrollY || window.pageYOffset || 0;
      parallaxItems.forEach((item) => {
        const factor = Number(item.dataset.parallax || 0.1);
        const intensity = 1.85;
        // O casal começa 80px abaixo do contador e sobe no máximo 68px.
        // Assim o movimento é perceptível sem atravessar a contagem.
        const offset = item.classList.contains('kp-home-couple')
          ? -Math.min(68, scrolled * 0.30)
          : scrolled * factor * intensity;
        const existing = item.dataset.baseTransform || '';
        item.style.transform = `${existing} translate3d(0, ${offset}px, 0)`;
      });
      ticking = false;
    };

    parallaxItems.forEach((item) => {
      const computed = window.getComputedStyle(item).transform;
      item.dataset.baseTransform = computed && computed !== 'none' ? computed : '';
    });

    const requestTick = () => {
      if (!ticking) {
        window.requestAnimationFrame(updateParallax);
        ticking = true;
      }
    };

    requestTick();
    window.addEventListener('scroll', requestTick, { passive: true });
    window.addEventListener('resize', requestTick);
  }
});
