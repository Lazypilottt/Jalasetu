import React from 'react';

function timeAgo(ts) {
  const seconds = Math.round((Date.now() - ts) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(ts).toLocaleDateString();
}

/**
 * Recent analyses stored in this browser. Restoring an entry reselects its
 * area and settings; the analysis itself is re-run on demand.
 */
export default function HistoryPanel({ entries, onRestore, onClear, disabled = false }) {
  if (!entries || entries.length === 0) return null;
  return (
    <div className="panel history-panel" role="region" aria-label="Recent analyses">
      <div className="panel-header">
        <div className="panel-title-group">
          <span className="panel-icon" aria-hidden="true">↺</span>
          <h3 className="panel-title">Recent analyses</h3>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClear} disabled={disabled}>
          Clear
        </button>
      </div>
      <ul className="history-list">
        {entries.map((entry) => (
          <li key={entry.id} className="history-item">
            <div className="history-item-main">
              <span className="history-item-title">
                {entry.site
                  ? `Score ${Math.round(entry.site.score)} · ${entry.site.latitude.toFixed(4)}, ${entry.site.longitude.toFixed(4)}`
                  : entry.status === 'no_suitable_site' ? 'No suitable site' : 'Analysis'}
              </span>
              <span className="history-item-meta">
                {entry.source} · {timeAgo(entry.at)}
                {typeof entry.catchmentHa === 'number' ? ` · ${entry.catchmentHa.toFixed(2)} ha catchment` : ''}
              </span>
            </div>
            {entry.area && (
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => onRestore(entry)}
                disabled={disabled}
                title="Reselect this area and its settings"
              >
                Restore
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
