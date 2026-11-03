import React, { useState } from 'react';

const ROLE_LABELS = {
  edge: 'Edge · frontend + climate',
  'stage-worker': 'Stage worker',
  gateway: 'Gateway · queue + scheduler',
};

function nodeState(node) {
  if (node.reachable === false) return { label: 'Unreachable', icon: '✕', tone: 'critical' };
  if (node.role === 'edge') return { label: 'Serving', icon: '●', tone: 'good' };
  if (node.capacity?.accepting) return { label: 'Accepting stages', icon: '●', tone: 'good' };
  if ((node.capacity?.in_flight || 0) > 0) return { label: 'Busy', icon: '◐', tone: 'warning' };
  return { label: 'Low headroom', icon: '▲', tone: 'warning' };
}

/**
 * Same-ramp meter: the fill carries severity, the track is a lighter step of
 * the same hue, and an optional tick marks a threshold. Values are text.
 */
function Meter({ label, used, budget, threshold, unit = 'MB', thresholdLabel }) {
  if (typeof used !== 'number' || typeof budget !== 'number' || budget <= 0) {
    return (
      <div className="meter">
        <div className="meter-header">
          <span className="meter-label">{label}</span>
          <span className="meter-value">measuring…</span>
        </div>
        <div className="meter-track meter-tone-neutral" />
      </div>
    );
  }
  const ratio = Math.min(1, Math.max(0, used / budget));
  const overThreshold = typeof threshold === 'number' && used > threshold;
  const tone = ratio >= 0.92 ? 'danger' : overThreshold ? 'warning' : 'accent';
  const title = `${label}: ${Math.round(used)} of ${Math.round(budget)} ${unit}` +
    (typeof threshold === 'number' ? ` (${thresholdLabel} at ${Math.round(threshold)} ${unit})` : '');
  return (
    <div className="meter" title={title}>
      <div className="meter-header">
        <span className="meter-label">{label}</span>
        <span className="meter-value">
          {Math.round(used)} <span className="meter-value-muted">/ {Math.round(budget)} {unit}</span>
        </span>
      </div>
      <div
        className={`meter-track meter-tone-${tone}`}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={Math.round(budget)}
        aria-valuenow={Math.round(used)}
        aria-valuetext={title}
      >
        <div className="meter-fill" style={{ width: `${ratio * 100}%` }} />
        {typeof threshold === 'number' && threshold > 0 && threshold < budget && (
          <div className="meter-threshold" style={{ left: `${(threshold / budget) * 100}%` }} />
        )}
      </div>
    </div>
  );
}

function NodeCard({ node, activeStage }) {
  const state = nodeState(node);
  const memory = node.capacity?.memory || {};
  const reserve = node.capacity?.stage_reserve_mb;
  const admitLine = typeof memory.budget_mb === 'number' && typeof reserve === 'number' && node.role !== 'edge'
    ? memory.budget_mb - reserve
    : undefined;
  const storage = node.storage || {};
  const isActive = Boolean(activeStage);

  return (
    <div className={`cluster-node ${isActive ? 'cluster-node-active' : ''}`}>
      <div className="cluster-node-header">
        <div className="cluster-node-title">
          <span className="cluster-node-name">{node.name}</span>
          <span className="cluster-node-role">{ROLE_LABELS[node.role] || node.role}</span>
        </div>
        <span className={`status-pill status-pill-${state.tone}`}>
          <span aria-hidden="true">{state.icon}</span> {state.label}
        </span>
      </div>

      {isActive && <div className="cluster-node-activity">Running: {activeStage}</div>}

      {node.reachable !== false ? (
        <>
          <Meter
            label="Memory"
            used={memory.used_mb}
            budget={memory.budget_mb}
            threshold={admitLine}
            thresholdLabel="admission limit"
          />
          <Meter label="Storage" used={storage.used_mb} budget={storage.budget_mb} />
          <dl className="cluster-node-stats">
            {node.role !== 'edge' && (
              <div>
                <dt>In flight</dt>
                <dd>{(node.capacity?.in_flight ?? 0) + (node.pending ?? 0)} / {node.capacity?.slots ?? '–'}</dd>
              </div>
            )}
            {node.role !== 'edge' && (
              <div>
                <dt>Stages run</dt>
                <dd>{node.stages_run ?? 0}</dd>
              </div>
            )}
            <div>
              <dt>Latency</dt>
              <dd>{node.local ? 'local' : typeof node.latency_ms === 'number' ? `${node.latency_ms} ms` : '–'}</dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="cluster-node-error">{node.last_error || 'Health check failed'}</p>
      )}
    </div>
  );
}

/**
 * Live view of the four-node deployment: per-node memory against the 500 MB
 * budget (with the admission limit marked), storage against 1.5 GB, and where
 * the running analysis currently is.
 *
 * @param {Object} props
 * @param {ReturnType<import('../hooks/useClusterStatus').default>} props.cluster
 * @param {{ stage?: string, node?: string } | null} [props.activeProgress]
 */
export default function ClusterPanel({ cluster, activeProgress = null }) {
  const [isOpen, setIsOpen] = useState(false);
  if (cluster.mode === 'single-node' || cluster.mode === 'loading') return null;

  const nodes = cluster.data?.nodes || [];
  const reachable = nodes.filter((n) => n.reachable !== false).length;
  const jobs = cluster.data?.jobs;
  const activeNode = activeProgress?.node;

  return (
    <div className="panel cluster-panel" role="region" aria-label="Cluster capacity">
      <button
        type="button"
        className="panel-header cluster-panel-toggle"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
      >
        <div className="panel-title-group">
          <span className="panel-icon" aria-hidden="true">⇄</span>
          <div className="cluster-panel-heading">
            <h3 className="panel-title">Cluster</h3>
            <span className="cluster-panel-summary">
              {cluster.mode === 'error' && !cluster.data
                ? 'Status unavailable'
                : `${reachable}/${nodes.length} nodes up${jobs ? ` · ${jobs.running} running, ${jobs.queued} queued` : ''}`}
            </span>
          </div>
        </div>
        <span className="cluster-panel-chevron" aria-hidden="true">{isOpen ? '▲' : '▼'}</span>
      </button>

      {isOpen && (
        <div className="panel-body cluster-panel-body">
          <p className="cluster-panel-help">
            Each stage runs on whichever node has a free slot and enough memory headroom under its
            500 MB budget. The tick on each memory bar is the admission limit.
          </p>
          <div className="cluster-node-grid">
            {nodes.map((node) => (
              <NodeCard
                key={node.name}
                node={node}
                activeStage={activeNode === node.name ? activeProgress?.stage : null}
              />
            ))}
          </div>
          {cluster.error && <p className="cluster-node-error">Last refresh failed: {cluster.error}</p>}
        </div>
      )}
    </div>
  );
}
