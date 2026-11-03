import React, { useState } from 'react';
import { PIPELINE_STAGES } from './PipelineProgress';
import {
  downloadText,
  exportFileStem,
  resultToGeoJSON,
  sitesToCsv,
} from '../utils/exportResults';
import { shareUrl } from '../utils/urlState';
import { INFRASTRUCTURE_CATEGORIES } from '../utils/settings';

const TERRAIN_LABELS = {
  uploaded_contours: 'Uploaded contours',
  bundled_contours: 'Demo contours',
  global_dem: 'Global DEM · ~30 m',
};
const CATEGORY_LABELS = Object.fromEntries(INFRASTRUCTURE_CATEGORIES.map((c) => [c.id, c.label.toLowerCase()]));
CATEGORY_LABELS.manual = 'marked zones';

function InfrastructureSummaryLine({ infrastructure }) {
  if (!infrastructure) return null;
  if (infrastructure.status === 'unavailable') {
    return <div className="run-summary-infra run-summary-infra-warning">Infrastructure could not be checked — verify on the ground.</div>;
  }
  const entries = Object.entries(infrastructure.counts || {});
  if (entries.length === 0) {
    return <div className="run-summary-infra">No mapped infrastructure in the surveyed {Math.round(infrastructure.survey_radius_m)} m.</div>;
  }
  return (
    <div className="run-summary-infra">
      Avoided {entries.map(([c, n]) => `${n} ${CATEGORY_LABELS[c] || c}`).join(', ')} ·{' '}
      {(infrastructure.excluded_area_m2 / 10000).toFixed(2)} ha masked
    </div>
  );
}

function formatSeconds(ms) {
  if (typeof ms !== 'number') return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/**
 * Run summary (where each stage ran, and how long) plus exports for the
 * current result: JSON, GeoJSON for QGIS/Google Earth, CSV, and a share link.
 */
export default function ResultsToolbar({ result, selectedArea }) {
  const [copied, setCopied] = useState(false);
  if (!result) return null;

  const stem = exportFileStem(result);
  const stages = result.execution?.stages || [];
  const hasSites = Boolean(result.recommended_site);

  const copyLink = async () => {
    const url = shareUrl(selectedArea || result.selected_area && {
      latitude: result.selected_area.latitude,
      longitude: result.selected_area.longitude,
      radiusM: result.selected_area.radius_m,
    });
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt('Copy this link', url);
    }
  };

  return (
    <div className="results-toolbar" role="region" aria-label="Run summary and exports">
      <div className="run-summary-badges">
        {result.terrain_source && (
          <span className={`source-badge source-${result.terrain_source}`}>{TERRAIN_LABELS[result.terrain_source] || result.terrain_source}</span>
        )}
        {result.rainfall?.recommended_design_rainfall_mm && (
          <span className="source-badge source-rain">Storm {Math.round(result.catchment?.design_rainfall_mm ?? result.rainfall.recommended_design_rainfall_mm)} mm</span>
        )}
      </div>
      <InfrastructureSummaryLine infrastructure={result.infrastructure} />

      {stages.length > 0 && (
        <div className="run-summary">
          <div className="run-summary-title">
            Computed in {formatSeconds(result.execution.total_ms)} across{' '}
            {[...new Set(stages.map((s) => s.node))].length} nodes
          </div>
          <ol className="run-summary-stages">
            {stages.map((s) => (
              <li key={s.stage} title={s.mode === 'local-degraded' ? 'No worker was reachable; the gateway ran this stage itself' : undefined}>
                <span className="run-summary-stage">{PIPELINE_STAGES.find((p) => p.key === s.stage)?.short || s.stage}</span>
                <span className="node-chip">{s.node}</span>
                <span className="run-summary-time">{formatSeconds(s.duration_ms)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="export-actions">
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={() => downloadText(`${stem}.geojson`, JSON.stringify(resultToGeoJSON(result)), 'application/geo+json')}
          disabled={!hasSites}
          title="Sites, pond footprints and catchment for QGIS or Google Earth"
        >
          GeoJSON
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={() => downloadText(`${stem}_sites.csv`, sitesToCsv(result), 'text/csv')}
          disabled={!hasSites}
          title="Ranked candidate sites as a spreadsheet"
        >
          CSV
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={() => downloadText(`${stem}.json`, JSON.stringify(result, null, 2), 'application/json')}
          title="Full analysis response"
        >
          JSON
        </button>
        {(selectedArea || result.selected_area) && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={copyLink} title="Link that reopens this selected area">
            {copied ? 'Link copied' : 'Copy link'}
          </button>
        )}
      </div>
    </div>
  );
}
