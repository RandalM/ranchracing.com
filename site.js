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
