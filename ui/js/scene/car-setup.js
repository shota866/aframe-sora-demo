export function configureCarForNet(carEl) {
  if (!carEl) return;
  carEl.removeAttribute('car-drive');
  carEl.removeAttribute('dynamic-body');
  const dyn = carEl.components?.['dynamic-body'];
  if (dyn && dyn.el) {
    dyn.el.removeAttribute('dynamic-body');
  }
}

