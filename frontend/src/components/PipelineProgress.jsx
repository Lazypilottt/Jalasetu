import React, { useEffect, useState } from 'react';

export const PIPELINE_STAGES = [
  { key: 'prepare', label: 'Parse contours & build DEM', short: 'Parse + DEM' },
  { key: 'analyze', label: 'Terrain analysis & site ranking', short: 'Terrain + rank' },
  { key: 'catchment', label: 'Catchment & runoff', short: 'Catchment' },
  { key: 'climate', label: 'Rainfall climatology', short: 'Climate' },
];

function formatMs(ms) {
  if (typeof ms !== 'number') return '';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

function useElapsed(running) {
  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [running]);
  return Math.max(0, now - startedAt);
}

/**
 * Live stepper for a distributed analysis job.
 *
 * With the single-node FastAPI backend there is no job progress, so only the
 * elapsed time and an indeterminate bar are shown.
 *
 * @param {Object} props
 * @param {import('../api/catchmentApi').AnalysisProgress|null} props.progress
 */
export default function PipelineProgress({ progress }) {
  const elapsed = useElapsed(true);
  const completed = new Map((progress?.stages || []).map((s) => [s.stage, s]));
  const queued = progress?.state === 'queued';

  let headline = 'Analyzing terrain and identifying catchment area…';
  if (queued) {
    headline = progress.queue_position > 0
      ? `Queued — position ${progress.queue_position}`
      : 'Queued — waiting for a free analysis slot';
  } else if (progress?.waiting_for_capacity) {
    headline = 'All nodes are busy — waiting for memory headroom';
  } else if (progress?.stage) {
    const stage = PIPELINE_STAGES.find((s) => s.key === progress.stage);
    headline = `${stage ? stage.label : progress.stage}${progress.node ? ` on ${progress.node}` : ''}`;
  }

  return (
    <div className="pipeline-progress" role="status" aria-live="polite">
      <div className="pipeline-progress-header">
        <div className="loading-spinner" aria-hidden="true"></div>
        <div className="pipeline-progress-text">
          <span className="loading-title">{headline}</span>
          <span className="loading-subtitle">Elapsed {formatMs(elapsed)}</span>
        </div>
      </div>

      {progress ? (
        <ol className="pipeline-steps">
          {PIPELINE_STAGES.map((stage) => {
            const done = completed.get(stage.key);
            const active = !done && progress.stage === stage.key;
            const state = done ? 'done' : active ? (progress.waiting_for_capacity ? 'waiting' : 'active') : 'pending';
            const node = done?.node || (active ? progress.node : null);
            const skipped = done?.attempts?.filter((a) => a.outcome !== 'degraded') || [];
            return (
              <li key={stage.key} className={`pipeline-step pipeline-step-${state}`}>
                <span className="pipeline-step-marker" aria-hidden="true">
                  {done ? '✓' : PIPELINE_STAGES.indexOf(stage) + 1}
                </span>
                <span className="pipeline-step-label">{stage.label}</span>
                <span className="pipeline-step-meta">
                  {node && <span className="node-chip">{node}</span>}
                  {done && <span className="pipeline-step-time">{formatMs(done.duration_ms)}</span>}
                </span>
                {skipped.length > 0 && (
                  <span className="pipeline-step-note">
                    Skipped {skipped.map((a) => `${a.node} (${a.outcome})`).join(', ')}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="loading-progress-bar-track">
          <div className="loading-progress-bar-fill"></div>
        </div>
      )}
    </div>
  );
}
