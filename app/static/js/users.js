(() => {
  const button = document.querySelector('[data-show-user-password]');
  button?.addEventListener('click', () => {
    const show = button.getAttribute('aria-pressed') !== 'true';
    document.querySelectorAll('.users-form [name="password"], .users-form [name="password_confirmation"]').forEach(input => {
      input.type = show ? 'text' : 'password';
    });
    button.setAttribute('aria-pressed', String(show));
    button.textContent = show ? 'Ocultar senha' : 'Mostrar senha';
  });
  document.querySelector('.users-form [aria-invalid="true"]')?.focus({ preventScroll: true });
})();
