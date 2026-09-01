import React, { useState, useMemo, useEffect } from 'react';

/**
 * ============================================================================
 * Pattern-to-User-Facing Caveat Translation Rules
 * ============================================================================
 *
 * Matches raw backend logs / status indicators and translates them into
 * non-technical, user-friendly plain-language bullet points and guidance.
 *
 * Rules table:
 *  - pattern: Regex matching specific backend log strings or warnings.
 *  - category: 'warning' (amber/caution) | 'info' (blue notice)
 *  - bullet: Plain-language 1-sentence explanation of what happened.
 *  - recommendation: Actionable guidance for village administrators / engineers.
 */
export const CAVEAT_TRANSLATION_RULES = [
  {
    id: 'no_suitable_site',
    pattern: /(no viable candidate|no candidate regions|no_suitable_site|no regions met)/i,
    category: 'warning',
    title: 'No Optimal Excavation Sites Identified',
    bullet:
      'Terrain slopes across the mapped area are too steep or lack sufficient natural hollows for standard pond excavation.',
    recommendation:
      'We recommend reviewing the map manually, uploading a contour file covering a wider valley area, or adjusting slope constraints.',
  },
  {
    id: 'relaxed_fallback',
    pattern: /(relaxed fallback|attempting relaxed fallback|initial criteria)/i,
    category: 'info',
    title: 'Relaxed Siting Criteria Applied',
    bullet:
      'Initial strict excavation criteria found no sweet-spots; thresholds were automatically relaxed to identify the best available candidate locations.',
    recommendation:
      'Verify whether the candidate footprint area and ground slope match your village construction capacity.',
  },
  {
    id: 'pysheds_hydrology_fallback',
    pattern: /(pysheds.*(error|attribute|fail)|falling back to native d8|basin_approximation)/i,
    category: 'info',
    title: 'Simplified Drainage Boundary Notice',
    bullet:
      'Catchment drainage was estimated using topographic slope approximation rather than continuous hydrological flow routing.',
    recommendation:
      'Use this boundary as a preliminary guide and verify local stream channels on-site.',
  },
  {
    id: 'catchment_failed',
    pattern: /(catchment delineation failed|failed to delineate)/i,
    category: 'warning',
    title: 'Catchment Delineation Incomplete',
    bullet:
      'Pond location was identified, but upstream drainage catchment could not be fully delineated from the provided contour bounds.',
    recommendation:
      'Consider uploading a larger contour file covering the surrounding upstream ridges.',
  },
  {
    id: 'skipped_features',
    pattern: /(skipped|missing elevation|unsupported geometry|no 3d coordinates)/i,
    category: 'info',
    title: 'Feature Notice',
    bullet:
      'Some map placemarks lacked elevation attributes or valid geometry and were skipped during elevation surface modeling.',
    recommendation:
      'Ensure contour map exports contain elevation data for all contour lines.',
  },
  {
    id: 'sparse_dem_sampling',
    pattern: /(sparse contour|fallback interpolation|dem grid error)/i,
    category: 'info',
    title: 'Interpolation Notice',
    bullet:
      'Contour spacing is wide; elevation surface was interpolated using adaptive grid resolution.',
    recommendation: null,
  },
];

/**
 * Extracts and translates backend logs / status into a concise list of user-facing caveats.
 * Returns an empty array for clean, complete analyses (ignoring normal operational logs).
 *
 * @param {string|null} [status] - Execution status ('success', 'no_suitable_site', 'partial_success', 'error').
 * @param {Array<string>} [notes=[]] - Raw processing notes from the backend response.
 * @returns {{ category: 'warning'|'info', title: string, bullets: Array<string>, recommendation: string|null } | null}
 */
export function extractCaveatsAndWarnings(status, notes = []) {
  const matchedRules = new Map();
  const rawList = Array.isArray(notes) ? notes : [];

  // 1. Check top-level execution status
  if (status === 'no_suitable_site') {
    const rule = CAVEAT_TRANSLATION_RULES.find((r) => r.id === 'no_suitable_site');
    if (rule) matchedRules.set(rule.id, rule);
  } else if (status === 'partial_success') {
    const rule = CAVEAT_TRANSLATION_RULES.find((r) => r.id === 'catchment_failed');
    if (rule) matchedRules.set(rule.id, rule);
  }

  // 2. Scan processing notes against defined translation patterns
  rawList.forEach((note) => {
    if (typeof note !== 'string') return;

    CAVEAT_TRANSLATION_RULES.forEach((rule) => {
      if (rule.pattern.test(note)) {
        matchedRules.set(rule.id, rule);
      }
    });

    // Capture uncategorized explicit warnings/errors if any
    const lower = note.toLowerCase();
    if (
      (lower.includes('warning:') || lower.includes('error:') || lower.includes('failed:')) &&
      !Array.from(matchedRules.values()).some((r) => r.pattern.test(note))
    ) {
      matchedRules.set(`custom-${note}`, {
        id: `custom-${note}`,
        category: 'warning',
        title: 'Processing Notice',
        bullet: note.replace(/^(warning|error|failed):\s*/i, ''),
        recommendation: null,
      });
    }
  });

  // If no caveats or warnings were identified (clean complete run), return null
  if (matchedRules.size === 0) {
    return null;
  }

  const rulesArray = Array.from(matchedRules.values());
  const hasWarning = rulesArray.some((r) => r.category === 'warning');
  const category = hasWarning ? 'warning' : 'info';

  const bullets = rulesArray.map((r) => r.bullet).slice(0, 2); // Max 1-2 concise bullet points
  const recommendation = rulesArray.find((r) => r.recommendation)?.recommendation || null;
  const title = rulesArray[0]?.title || (hasWarning ? 'Analysis Notice' : 'Processing Information');

  return {
    category,
    title,
    bullets,
    recommendation,
  };
}

/**
 * ProcessingNotesBanner Component
 *
 * Renders a small, dismissible banner summarizing any caveats or fallbacks in plain language.
 * Only renders when there is a noteworthy caveat or fallback (remains hidden for clean runs).
 *
 * @param {Object} props
 * @param {string} [props.status] - CatchmentResponse status ('success', 'no_suitable_site', 'partial_success', etc.).
 * @param {Array<string>} [props.notes=[]] - Array of processing_notes strings.
 * @param {Object} [props.response] - CatchmentResponse object (alternative all-in-one prop).
 */
export default function ProcessingNotesBanner({ status, notes = [], response }) {
  const [isDismissed, setIsDismissed] = useState(false);

  // Extract effective status and notes from props or response object
  const effectiveStatus = status || response?.status || null;
  const effectiveNotes = notes?.length > 0 ? notes : response?.processing_notes || [];

  // Reset dismissal whenever a new analysis response arrives
  const notesKey = useMemo(() => {
    return `${effectiveStatus}-${effectiveNotes.join(';')}`;
  }, [effectiveStatus, effectiveNotes]);

  useEffect(() => {
    setIsDismissed(false);
  }, [notesKey]);

  // Extract user-facing caveats
  const caveatData = useMemo(() => {
    return extractCaveatsAndWarnings(effectiveStatus, effectiveNotes);
  }, [effectiveStatus, effectiveNotes]);

  // Don't render if dismissed or if there are no caveats (clean run)
  if (isDismissed || !caveatData) {
    return null;
  }

  const { category, title, bullets, recommendation } = caveatData;
  const isWarning = category === 'warning';

  return (
    <div
      className={`processing-notes-banner ${isWarning ? 'banner-warning' : 'banner-info'}`}
      role="region"
      aria-label="Analysis Caveats"
    >
      {/* Banner Header */}
      <div className="notes-header">
        <div className="notes-title-group">
          <span className="notes-icon">{isWarning ? '⚠️' : 'ℹ️'}</span>
          <span className="notes-title">{title}</span>
        </div>
        <button
          className="notes-dismiss-btn"
          type="button"
          onClick={() => setIsDismissed(true)}
          title="Dismiss notice"
          aria-label="Dismiss notice"
        >
          ✕
        </button>
      </div>

      {/* Translated Short Bullet Points */}
      <ul className="notes-list">
        {bullets.map((bullet, idx) => (
          <li key={idx} className="note-item">
            {bullet}
          </li>
        ))}
      </ul>

      {/* Planning Recommendation */}
      {recommendation && (
        <div className="notes-recommendation">
          <strong>Guidance:</strong> {recommendation}
        </div>
      )}
    </div>
  );
}
