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

  const priceNodes = document.querySelectorAll('[data-tariff-price]');
  if (priceNodes.length === 0) {
    return;
  }

  const formatRubPrice = function (value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return null;
    }
    return value.toLocaleString('ru-RU') + ' ₽';
  };

  const updateMetaDescription = function (tariffs) {
    const target = document.querySelector('meta[data-price-meta-description]');
    if (!target) {
      return;
    }

    const t0 = formatRubPrice(tariffs.T0);
    const t1 = formatRubPrice(tariffs.T1);
    const t2 = formatRubPrice(tariffs.T2);
    const t3 = formatRubPrice(tariffs.T3);
    if (!t0 || !t1 || !t2 || !t3) {
      return;
    }

    target.setAttribute(
      'content',
      'Тарифы Нумерология-бот: превью ' + t0 + ', «В чём твоя сила?» ' + t1 + ', «Где твои деньги?» ' + t2 + ' и «Твой путь к себе!» ' + t3 + '.'
    );
  };

  const updateJsonLd = function (tariffs, currency) {
    const jsonLd = document.getElementById('prices-jsonld');
    if (!jsonLd) {
      return;
    }

    let payload;
    try {
      payload = JSON.parse(jsonLd.textContent || '{}');
    } catch (_error) {
      return;
    }

    if (!payload || !Array.isArray(payload.offers)) {
      return;
    }

    payload.offers = payload.offers.map(function (offer, index) {
      const key = index === 0 ? 'T1' : index === 1 ? 'T2' : 'T3';
      const price = tariffs[key];
      if (typeof price !== 'number' || !Number.isFinite(price)) {
        return offer;
      }
      return Object.assign({}, offer, {
        price: String(price),
        priceCurrency: currency || 'RUB',
      });
    });

    jsonLd.textContent = JSON.stringify(payload);
  };

  fetch('/api/public/tariffs', { cache: 'no-store' })
    .then(function (response) {
      if (!response.ok) {
        throw new Error('prices_api_unavailable');
      }
      return response.json();
    })
    .then(function (payload) {
      const tariffs = (payload && payload.tariffs) || {};
      const currency = (payload && payload.currency) || 'RUB';

      priceNodes.forEach(function (node) {
        const tariff = node.getAttribute('data-tariff-price');
        if (!tariff) {
          return;
        }
        const value = tariffs[tariff];
        const formatted = formatRubPrice(value);
        if (!formatted) {
          return;
        }
        node.textContent = formatted;
      });

      updateMetaDescription(tariffs);
      updateJsonLd(tariffs, currency);
    })
    .catch(function () {
      // Оставляем fallback-цены из статического HTML.
    });
})();
