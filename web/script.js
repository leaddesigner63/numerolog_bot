(function () {
  const menuButton = document.querySelector('[data-menu-button]');
  const menuNavId = menuButton ? menuButton.getAttribute('aria-controls') : null;
  const nav = menuNavId
    ? document.getElementById(menuNavId)
    : document.querySelector('[data-main-nav]');

  if (menuButton && nav) {
    if (!nav.id) {
      nav.id = 'main-nav';
    }

    if (!menuButton.getAttribute('aria-controls')) {
      menuButton.setAttribute('aria-controls', nav.id);
    }

    const syncMenuState = function (expanded) {
      menuButton.setAttribute('aria-expanded', String(expanded));
      nav.classList.toggle('open', expanded);
      menuButton.setAttribute('aria-label', expanded ? 'Закрыть меню навигации' : 'Открыть меню навигации');
    };

    syncMenuState(nav.classList.contains('open'));

    menuButton.addEventListener('click', function () {
      const expanded = menuButton.getAttribute('aria-expanded') === 'true';
      syncMenuState(!expanded);
    });
  }

  const faqItems = document.querySelectorAll('.faq-item');
  faqItems.forEach(function (item) {
    const button = item.querySelector('button');
    const answer = item.querySelector('.faq-answer');
    if (!button || !answer) return;

    button.addEventListener('click', function () {
      const isOpen = item.classList.contains('open');
      faqItems.forEach(function (other) {
        const otherButton = other.querySelector('button');
        const otherAnswer = other.querySelector('.faq-answer');
        other.classList.remove('open');
        if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
        if (otherAnswer) otherAnswer.setAttribute('hidden', '');
      });

      if (!isOpen) {
        item.classList.add('open');
        button.setAttribute('aria-expanded', 'true');
        answer.removeAttribute('hidden');
      }
    });
  });
})();
