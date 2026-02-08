(() => {
  const faqItems = document.querySelectorAll('.faq-item');

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
})();
