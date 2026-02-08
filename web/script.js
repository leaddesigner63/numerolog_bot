(() => {
  const DEFAULT_CONTENT = {
    meta: {
      title: 'ИИ-аналитик личных данных — Telegram',
      description: 'Персональный аналитический разбор в Telegram: выберите тариф T0–T3 и получите отчёт за несколько минут.',
      brand: 'Numerolog Bot MVP',
    },
  };

  const getByPath = (obj, path) => path.split('.').reduce((acc, key) => (acc && key in acc ? acc[key] : null), obj);

  const setStaticContent = (content) => {
    document.querySelectorAll('[data-content]').forEach((element) => {
      const value = getByPath(content, element.dataset.content);
      if (typeof value === 'string') {
        element.textContent = value;
      }
    });
  };

  const renderBenefits = (content) => {
    const target = document.querySelector('#benefits-grid');
    if (!target) return;
    target.innerHTML = '';
    (content.benefits?.items || []).forEach((item) => {
      const article = document.createElement('article');
      article.className = 'card';
      article.innerHTML = `<h3>${item.title || ''}</h3><p>${item.description || ''}</p>`;
      target.appendChild(article);
    });
  };

  const renderTariffs = (content) => {
    const target = document.querySelector('#tariffs-grid');
    if (!target) return;
    target.innerHTML = '';
    (content.tariffs?.items || []).forEach((tariff) => {
      const isRecommended = Boolean(tariff.badge);
      const article = document.createElement('article');
      article.className = `card tariff${isRecommended ? ' tariff-recommended' : ''}`;
      article.innerHTML = `${isRecommended ? `<span class="badge">${tariff.badge}</span>` : ''}
        <p class="tariff-title">${tariff.title || ''}</p>
        <p class="tariff-price">${tariff.price || ''}</p>
        <p>${tariff.description || ''}</p>
        <a class="btn btn-primary js-telegram-cta js-tariff-cta" href="https://t.me/your_bot_username" data-placement="${tariff.placement || 'tariff_unknown'}" data-tariff="${tariff.id || 'na'}">${tariff.cta || 'Выбрать'}</a>`;
      target.appendChild(article);
    });
  };

  const renderDisclaimers = (content) => {
    const target = document.querySelector('#disclaimer-list');
    if (!target) return;
    target.innerHTML = '';
    (content.disclaimers?.items || []).forEach((item) => {
      const li = document.createElement('li');
      li.textContent = item;
      target.appendChild(li);
    });
  };

  const renderFaq = (content) => {
    const target = document.querySelector('#faq-list');
    if (!target) return;
    target.innerHTML = '';
    (content.faq?.items || []).forEach((item) => {
      const details = document.createElement('details');
      details.className = 'faq-item';
      details.innerHTML = `<summary>${item.question || ''}</summary><p>${item.answer || ''}</p>`;
      target.appendChild(details);
    });
  };

  const applyMeta = (content) => {
    const title = content.meta?.title || DEFAULT_CONTENT.meta.title;
    const description = content.meta?.description || DEFAULT_CONTENT.meta.description;
    const brand = content.meta?.brand || DEFAULT_CONTENT.meta.brand;
    document.title = title;
    const metaDescription = document.querySelector('meta[name="description"]');
    if (metaDescription) metaDescription.setAttribute('content', description);
    const footerBrand = document.querySelector('#footer-brand');
    if (footerBrand) footerBrand.textContent = `© ${brand}`;
  };

  const toSafeToken = (value, maxLength = 12) => {
    const normalized = String(value || 'na').trim().toLowerCase().replace(/[^a-z0-9_-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
    return (normalized || 'na').slice(0, maxLength);
  };

  const readAttribution = () => {
    const params = new URLSearchParams(window.location.search || '');
    return {
      source: toSafeToken(params.get('utm_source') || params.get('source') || 'na'),
      campaign: toSafeToken(params.get('utm_campaign') || params.get('campaign') || 'na'),
      medium: toSafeToken(params.get('utm_medium') || 'na'),
      content: toSafeToken(params.get('utm_content') || 'na'),
      term: toSafeToken(params.get('utm_term') || 'na'),
    };
  };

  const attribution = readAttribution();

  const makeStartPayload = (placement) => {
    const safePlacement = toSafeToken(placement || 'unknown');
    let payload = ['lnd', `src_${attribution.source}`, `cmp_${attribution.campaign}`, `pl_${safePlacement}`].join('.');
    if (payload.length > 64) {
      payload = ['lnd', `src_${toSafeToken(attribution.source, 8)}`, `cmp_${toSafeToken(attribution.campaign, 8)}`, `pl_${toSafeToken(safePlacement, 8)}`].join('.');
    }
    return payload.slice(0, 64);
  };

  const buildTelegramUrl = (baseUrl, placement) => {
    try {
      const url = new URL(baseUrl);
      url.searchParams.set('start', makeStartPayload(placement));
      return url.toString();
    } catch (_error) {
      return baseUrl;
    }
  };

  const emitAnalytics = (eventName, payload = {}) => {
    const eventPayload = {
      event: eventName,
      event_id:
        (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' && crypto.randomUUID()) ||
        `evt_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`,
      ts: new Date().toISOString(),
      page: window.location.href,
      source: attribution.source,
      campaign: attribution.campaign,
      medium: attribution.medium,
      content: attribution.content,
      term: attribution.term,
      ...payload,
    };
    if (Array.isArray(window.dataLayer)) window.dataLayer.push(eventPayload);
    if (typeof window.gtag === 'function') window.gtag('event', eventName, eventPayload);
    return eventPayload;
  };

  const bindInteractions = () => {
    const faqItems = document.querySelectorAll('.faq-item');
    const faqSection = document.querySelector('#faq');
    const heroSection = document.querySelector('.hero');
    const telegramCtas = document.querySelectorAll('.js-telegram-cta');
    const tariffCtas = document.querySelectorAll('.js-tariff-cta');

    faqItems.forEach((item) => {
      item.addEventListener('toggle', () => {
        if (!item.open) return;
        faqItems.forEach((other) => {
          if (other !== item) other.open = false;
        });
      });
    });

    telegramCtas.forEach((cta) => {
      const placement = cta.dataset.placement || 'unknown';
      const nextUrl = buildTelegramUrl(cta.href, placement);
      cta.href = nextUrl;
      cta.addEventListener('click', () => {
        const startPayload = new URL(nextUrl).searchParams.get('start') || 'na';
        emitAnalytics('landing_cta_click', { placement, target: nextUrl, start_payload: startPayload });
      });
    });

    tariffCtas.forEach((cta) => {
      cta.addEventListener('click', () => {
        const placement = cta.dataset.placement || 'unknown';
        const tariff = toSafeToken(cta.dataset.tariff || 'na', 4);
        emitAnalytics('landing_tariff_click', {
          placement,
          tariff,
          target: cta.href,
          start_payload: new URL(cta.href).searchParams.get('start') || 'na',
        });
      });
    });

    const observeSectionOnce = (element, eventName, sectionName) => {
      if (!element || typeof IntersectionObserver === 'undefined') return;
      let sent = false;
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (sent || !entry.isIntersecting) return;
            sent = true;
            emitAnalytics(eventName, { section: sectionName });
            observer.disconnect();
          });
        },
        { threshold: 0.35 }
      );
      observer.observe(element);
    };

    observeSectionOnce(heroSection, 'landing_hero_view', 'hero');
    observeSectionOnce(faqSection, 'landing_faq_reach', 'faq');
  };

  const init = async () => {
    let content = DEFAULT_CONTENT;
    try {
      const response = await fetch('content/landing-content.json', { cache: 'no-store' });
      if (response.ok) {
        const payload = await response.json();
        content = { ...DEFAULT_CONTENT, ...payload };
      }
    } catch (_error) {
      content = DEFAULT_CONTENT;
    }

    applyMeta(content);
    setStaticContent(content);
    renderBenefits(content);
    renderTariffs(content);
    renderDisclaimers(content);
    renderFaq(content);
    bindInteractions();
  };

  init();
})();
