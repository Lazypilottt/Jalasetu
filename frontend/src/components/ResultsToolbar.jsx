import React, { useState } from 'react';
import { PIPELINE_STAGES } from './PipelineProgress';
import {
  downloadText,
  exportFileStem,
  resultToGeoJSON,
  sitesToCsv,
} from '../utils/exportResults';
import { shareUrl } from '../utils/urlState';

function formatSeconds(ms) {
  return typeof ms === 'number' ? `${(ms / 1000).toFixed(1)} s` : null;
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
