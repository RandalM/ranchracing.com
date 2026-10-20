// About drop-down: click/tap to toggle, Escape or outside click to close.
document.querySelectorAll('.dropdown').forEach((dd) => {
  const btn = dd.querySelector('.dd-toggle');
  const menu = dd.querySelector('.dd-menu');
  const setOpen = (open) => {
    btn.setAttribute('aria-expanded', String(open));
    menu.classList.toggle('open', open);
  };
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    setOpen(btn.getAttribute('aria-expanded') !== 'true');
  });
  document.addEventListener('click', (e) => { if (!dd.contains(e.target)) setOpen(false); });
  dd.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { setOpen(false); btn.focus(); }
  });
});

const year = document.getElementById('year');
if (year) year.textContent = new Date().getFullYear();

// Formspree forms: submit in the background and show the result under the button.
document.querySelectorAll('form.js-formspree').forEach((form) => {
  const status = form.querySelector('.form-status');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    status.className = 'form-status';
    status.textContent = 'Sending…';
    try {
      const res = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { Accept: 'application/json' }
      });
      if (!res.ok) throw new Error();
      form.reset();
      status.className = 'form-status ok';
      status.textContent = 'Thanks! Your message is on its way. We\'ll be in touch soon.';
    } catch {
      status.className = 'form-status err';
      status.textContent = 'Something went wrong sending that. Please try again in a moment.';
    } finally {
      btn.disabled = false;
    }
  });
});
