(() => {
  const faqItems = document.querySelectorAll('.faq-item');
  const faqSection = document.querySelector('#faq');
  const heroSection = document.querySelector('.hero');
  const telegramCtas = document.querySelectorAll('.js-telegram-cta');
  const tariffCtas = document.querySelectorAll('.js-tariff-cta');

  const toSafeToken = (value, maxLength = 12) => {
    const normalized = String(value || 'na')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
    return (normalized || 'na').slice(0, maxLength);
  };

  const readAttribution = () => {
    const params = new URLSearchParams(window.location.search || '');
    const source = toSafeToken(params.get('utm_source') || params.get('source') || 'na');
    const campaign = toSafeToken(params.get('utm_campaign') || params.get('campaign') || 'na');
    const medium = toSafeToken(params.get('utm_medium') || 'na');
    const content = toSafeToken(params.get('utm_content') || 'na');
    const term = toSafeToken(params.get('utm_term') || 'na');
    return {
      source,
      campaign,
      medium,
      content,
      term,
    };
  };

  const attribution = readAttribution();

  const makeStartPayload = (placement) => {
    const safePlacement = toSafeToken(placement || 'unknown');
    const parts = [
      'lnd',
      `src_${attribution.source}`,
      `cmp_${attribution.campaign}`,
      `pl_${safePlacement}`,
    ];
    let payload = parts.join('.');

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

    if (Array.isArray(window.dataLayer)) {
      window.dataLayer.push(eventPayload);
    }

    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, eventPayload);
    }

    return eventPayload;
  };

  faqItems.forEach((item) => {
    item.addEventListener('toggle', () => {
      if (!item.open) {
        return;
      }
      faqItems.forEach((other) => {
        if (other !== item) {
          other.open = false;
        }
      });
    });
  });

  telegramCtas.forEach((cta) => {
    const placement = cta.dataset.placement || 'unknown';
    const nextUrl = buildTelegramUrl(cta.href, placement);
    cta.href = nextUrl;

    cta.addEventListener('click', () => {
      const startPayload = new URL(nextUrl).searchParams.get('start') || 'na';
      emitAnalytics('landing_cta_click', {
        placement,
        target: nextUrl,
        start_payload: startPayload,
      });
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
    if (!element || typeof IntersectionObserver === 'undefined') {
      return;
    }

    let sent = false;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (sent || !entry.isIntersecting) {
            return;
          }
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
})();
