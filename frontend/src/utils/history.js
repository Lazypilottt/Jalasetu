/**
 * Recent analyses kept in this browser only. Stores a compact summary, not the
 * full response (which can be several MB with contours and the DEM mesh).
 */

const STORAGE_KEY = 'jalasetu.history.v1';
const MAX_ENTRIES = 8;

export function loadHistory() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Private mode or quota exceeded: history is a convenience only.
  }
}

export function summarizeResult(result, { fileName, settings, selectedArea }) {
  const site = result?.recommended_site;
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    at: Date.now(),
    status: result?.status,
    source: fileName || 'Demo contours',
    area: selectedArea
      ? { latitude: selectedArea.latitude, longitude: selectedArea.longitude, radiusM: selectedArea.radiusM }
      : null,
    site: site
      ? {
          latitude: site.latitude,
          longitude: site.longitude,
          score: site.suitability_score,
          storage: site.storage_capacity_m3,
        }
      : null,
    catchmentHa: result?.catchment?.area_hectares ?? null,
    runoffM3: result?.catchment?.estimated_runoff_volume_m3 ?? null,
    totalMs: result?.execution?.total_ms ?? null,
    nodes: [...new Set((result?.execution?.stages || []).map((s) => s.node))],
    settings,
  };
}

export function addHistoryEntry(entry) {
  const next = [entry, ...loadHistory()].slice(0, MAX_ENTRIES);
  saveHistory(next);
  return next;
}

export function clearHistory() {
  saveHistory([]);
  return [];
}
