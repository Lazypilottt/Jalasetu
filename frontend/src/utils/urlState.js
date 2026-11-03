/**
 * Shareable selection state in the URL hash: #lat=21.25170&lon=81.29700&r=250
 * Only the selected area is shared; the analysis is re-run by the recipient.
 */

export function readSelectionFromHash(hash = window.location.hash) {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const latitude = Number(params.get('lat'));
  const longitude = Number(params.get('lon'));
  const radiusM = Number(params.get('r'));
  if (!params.has('lat') || !params.has('lon')) return null;
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return { latitude, longitude, radiusM: Number.isFinite(radiusM) && radiusM > 0 ? radiusM : null };
}

export function selectionHash(area) {
  if (!area) return '';
  const params = new URLSearchParams({
    lat: area.latitude.toFixed(5),
    lon: area.longitude.toFixed(5),
    r: String(Math.round(area.radiusM)),
  });
  return `#${params.toString()}`;
}

export function writeSelectionToHash(area) {
  const hash = selectionHash(area);
  const url = `${window.location.pathname}${window.location.search}${hash}`;
  window.history.replaceState(null, '', url);
}

export function shareUrl(area) {
  return `${window.location.origin}${window.location.pathname}${selectionHash(area)}`;
}
