document.addEventListener('DOMContentLoaded', () => {
  // Mobile Menu Toggle
  const toggle = document.querySelector('.mobile-toggle');
  const nav = document.querySelector('.nav-links');
  
  if(toggle && nav) {
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

  // Smooth Scroll for Anchors
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if(target) target.scrollIntoView({ behavior: 'smooth' });
    });
  });
});
