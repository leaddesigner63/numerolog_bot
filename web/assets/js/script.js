document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('.mobile-toggle');
  const nav = document.querySelector('.nav-links');

  if (toggle && nav) {
    const setMenuState = (isOpen) => {
      nav.classList.toggle('active', isOpen);
      toggle.setAttribute('aria-expanded', String(isOpen));
    };

    setMenuState(false);

    toggle.addEventListener('click', () => {
      setMenuState(!nav.classList.contains('active'));
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && nav.classList.contains('active')) {
        setMenuState(false);
        toggle.focus();
      }
    });

    document.addEventListener('click', (event) => {
      if (!nav.classList.contains('active')) {
        return;
      }

      if (!nav.contains(event.target) && !toggle.contains(event.target)) {
        setMenuState(false);
      }
    });

    nav.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => setMenuState(false));
    });
  }

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', function smoothScroll(e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({ behavior: 'smooth' });
      }
    });
  });

  const TELEGRAM_BOT_URL = 'https://t.me/AIreadUbot';
  const trackingSessionId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const readAttribution = () => {
    const params = new URLSearchParams(window.location.search || '');

    return {
      source: params.get('utm_source') || params.get('source') || 'na',
      campaign: params.get('utm_campaign') || params.get('campaign') || 'na',
    };
  };

  const attribution = readAttribution();

  const buildTelegramStartPayload = (placement) => {
    const source = attribution.source || 'na';
    const campaign = attribution.campaign || 'na';
    const safePlacement = placement || 'na';

    return `src_${source}cmp_${campaign}pl_${safePlacement}`;
  };

  const buildTelegramTargetUrl = (placement) => {
    const startPayload = buildTelegramStartPayload(placement);
    return `${TELEGRAM_BOT_URL}?start=${encodeURIComponent(startPayload)}`;
  };

  const trackEvent = (eventName, payload) => {
    const eventPayload = {
      event: eventName,
      event_id: `${trackingSessionId}-${Date.now()}`,
      ts: new Date().toISOString(),
      page: window.location.href,
      source: attribution.source,
      campaign: attribution.campaign,
      ...payload,
    };

    if (Array.isArray(window.dataLayer)) {
      window.dataLayer.push(eventPayload);
    }

    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, eventPayload);
    }
  };

  document.querySelectorAll('[data-telegram-cta], a.btn[href*="t.me/"]').forEach((cta) => {
    if (!cta.hasAttribute('data-telegram-cta')) {
      cta.setAttribute('data-telegram-cta', '');
    }

    cta.addEventListener('click', (event) => {
      event.preventDefault();

      const placement = cta.dataset.placement || 'na';
      const tariff = cta.dataset.tariff || 'na';
      const targetUrl = buildTelegramTargetUrl(placement);
      const eventName = cta.hasAttribute('data-tariff') ? 'landing_tariff_click' : 'landing_cta_click';

      cta.setAttribute('href', targetUrl);

      trackEvent(eventName, {
        tariff,
        placement,
        target: targetUrl,
      });

      window.location.href = targetUrl;
    });
  });

  const sticky = document.querySelector('[data-sticky-cta]');
  const finalCtaZone = document.querySelector('[data-final-cta-zone]');

  if (sticky && finalCtaZone) {
    const toggleStickyVisibility = (hideSticky) => {
      sticky.classList.toggle('is-hidden', hideSticky);
      sticky.setAttribute('aria-hidden', String(hideSticky));
    };

    if (typeof window.IntersectionObserver === 'function') {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            toggleStickyVisibility(entry.isIntersecting);
          });
        },
        { threshold: 0.25 }
      );

      observer.observe(finalCtaZone);
    } else {
      const fallbackCheck = () => {
        const rect = finalCtaZone.getBoundingClientRect();
        const isVisible = rect.top < window.innerHeight && rect.bottom > 0;
        toggleStickyVisibility(isVisible);
      };

      window.addEventListener('scroll', fallbackCheck, { passive: true });
      window.addEventListener('resize', fallbackCheck);
      fallbackCheck();
    }
  }
});
