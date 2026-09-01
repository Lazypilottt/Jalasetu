import React, { useState } from 'react';

/**
 * Derives a plain-language heuristic explanation for the suitability score.
 * Clearly labeled as a display heuristic.
 *
 * @param {number} score - Suitability score (0 - 100).
 * @param {number} [slopeDeg] - Terrain slope in degrees.
 * @returns {string} One-sentence plain-language explanation.
 */
export function deriveSiteSuitabilityInsight(score, slopeDeg) {
  if (typeof score !== 'number') {
    return 'Evaluated terrain candidate for village pond excavation.';
  }
  const slopeNote = typeof slopeDeg === 'number' ? `gentle ${slopeDeg.toFixed(1)}° slope` : 'favorable slope';

  if (score >= 88) {
    return `Optimal site — deep natural bowl depression with ${slopeNote} and high natural water accumulation potential.`;
  }
  if (score >= 70) {
    return `Good site — flat, low-lying ground with ${slopeNote} and solid upstream catchment drainage.`;
  }
  if (score >= 50) {
    return `Moderate site — viable excavation conditions with ${slopeNote}, suitable for standard community pond excavation.`;
  }
  return `Marginal site — candidate meeting minimal baseline requirements, may require deeper excavation or retaining bunds.`;
}

/**
 * Returns qualitative tier information and CSS classes for a given suitability score.
 *
 * @param {number} score - Suitability score (0 - 100).
 * @returns {{ tierLabel: string, tierClass: string, fillClass: string }}
 */
export function getScoreTier(score) {
  const num = typeof score === 'number' ? score : 0;
  if (num >= 88) {
    return { tierLabel: 'Optimal', tierClass: 'score-tier-excellent', fillClass: 'fill-excellent' };
  }
  if (num >= 70) {
    return { tierLabel: 'Good', tierClass: 'score-tier-good', fillClass: 'fill-good' };
  }
  if (num >= 50) {
    return { tierLabel: 'Moderate', tierClass: 'score-tier-moderate', fillClass: 'fill-moderate' };
  }
  return { tierLabel: 'Marginal', tierClass: 'score-tier-marginal', fillClass: 'fill-marginal' };
}

/**
 * SiteSummaryPanel Component
 *
 * Displays a clean, non-technical summary card for the #1 recommended pond site,
 * including a visual suitability score bar, plain-language heuristic rationale,
 * key terrain metrics, and a collapsible list of alternative candidate locations
 * with interactive "Show on Map" panning triggers.
 *
 * @param {Object} props
 * @param {Object|null} [props.recommendedSite] - Top-ranked candidate pond site (#1).
 * @param {Array} [props.alternativeSites=[]] - Alternative candidate pond sites.
 * @param {Function} [props.onSelectSite] - Callback invoked when a site is clicked to focus/pan on map.
 * @param {Function} [props.onPanToSite] - Alias for onSelectSite.
 */
export default function SiteSummaryPanel({
  recommendedSite = null,
  alternativeSites = [],
  onSelectSite,
  onPanToSite,
}) {
  const [isAlternativesOpen, setIsAlternativesOpen] = useState(false);

  const handleFocus = (site) => {
    if (typeof onSelectSite === 'function') {
      onSelectSite(site);
    }
    if (typeof onPanToSite === 'function') {
      onPanToSite(site);
    }
  };

  // Graceful empty state before any file is uploaded or analyzed
  if (!recommendedSite) {
    return (
      <div className="panel site-summary-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <span className="panel-icon">⭐</span>
            <h3 className="panel-title">Recommended Pond Location</h3>
          </div>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <span className="empty-state-icon">📍</span>
            <p className="empty-state-text">
              Upload a contour map to identify and rank optimal farm pond excavation sites.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const { tierLabel, tierClass, fillClass } = getScoreTier(recommendedSite.suitability_score);
  const scorePercent = Math.min(100, Math.max(0, recommendedSite.suitability_score || 0));
  const hasAlternatives = Array.isArray(alternativeSites) && alternativeSites.length > 0;

  return (
    <div className="panel site-summary-panel">
      {/* Panel Header */}
      <div className="panel-header">
        <div className="panel-title-group">
          <span className="panel-icon">⭐</span>
          <h3 className="panel-title">Recommended Pond Location</h3>
        </div>
        <span className="score-tier-badge score-tier-excellent">Rank #1 Top Pick</span>
      </div>

      {/* Panel Body */}
      <div className="panel-body">
        <div className="site-metrics-card">
          {/* Visual Suitability Score Card */}
          <div className="site-score-visual-card">
            <div className="score-visual-header">
              <div className="score-visual-left">
                <span className="score-main-number">{recommendedSite.suitability_score}</span>
                <span className="score-max-label">/ 100</span>
              </div>
              <span className={`score-tier-badge ${tierClass}`}>{tierLabel} Suitability</span>
            </div>

            {/* Visual Progress Bar */}
            <div className="score-progress-bar-track" title={`Suitability: ${recommendedSite.suitability_score}/100`}>
              <div
                className={`score-progress-bar-fill ${fillClass}`}
                style={{ width: `${scorePercent}%` }}
              ></div>
            </div>

            {/* Plain Language Rationale */}
            <div className="site-explanation-box">
              <p className="explanation-text">
                {deriveSiteSuitabilityInsight(recommendedSite.suitability_score, recommendedSite.slope_deg)}
              </p>
              <span className="explanation-heuristic-tag">
                Display heuristic based on local depression depth and ground slope
              </span>
            </div>
          </div>

          {/* Key Metric Details Grid */}
          <div className="metrics-grid">
            <div className="metric-item">
              <span className="metric-label">Pond Footprint</span>
              <span className="metric-val">
                {recommendedSite.area_m2?.toLocaleString()} m²{' '}
                <span className="metric-sub-text">
                  ({((recommendedSite.area_m2 || 0) / 10000).toFixed(2)} ha)
                </span>
              </span>
            </div>

            <div className="metric-item">
              <span className="metric-label">Ground Elevation</span>
              <span className="metric-val">{recommendedSite.elevation_m?.toFixed(1)} m</span>
            </div>

            <div className="metric-item">
              <span className="metric-label">Ground Slope</span>
              <span className="metric-val">{recommendedSite.slope_deg?.toFixed(1)}°</span>
            </div>

            {recommendedSite.storage_capacity_m3 !== undefined && recommendedSite.storage_capacity_m3 !== null && (
              <div className="metric-item">
                <span className="metric-label">Storage Capacity</span>
                <span className="metric-val" title="Estimated pond water storage capacity at 2m design depth">
                  {recommendedSite.storage_capacity_m3?.toLocaleString()} m³
                </span>
              </div>
            )}

            {recommendedSite.cut_volume_m3 !== undefined && recommendedSite.cut_volume_m3 !== null && (
              <div className="metric-item">
                <span className="metric-label">Excavation Cut Volume</span>
                <span className="metric-val" title="Earthwork excavation volume required">
                  {recommendedSite.cut_volume_m3?.toLocaleString()} m³
                </span>
              </div>
            )}

            {recommendedSite.storage_efficiency_ratio !== undefined && recommendedSite.storage_efficiency_ratio !== null && (
              <div className="metric-item">
                <span className="metric-label">Storage / Cut Efficiency</span>
                <span className="metric-val" title="Ratio of stored water volume to required earthwork cut">
                  {recommendedSite.storage_efficiency_ratio?.toFixed(2)}×
                </span>
              </div>
            )}

            {recommendedSite.mean_twi !== undefined && recommendedSite.mean_twi !== null && (
              <div className="metric-item">
                <span className="metric-label">Topographic Wetness (TWI)</span>
                <span className="metric-val" title="Natural terrain moisture and flow convergence index">
                  {recommendedSite.mean_twi?.toFixed(1)}
                </span>
              </div>
            )}

            <div className="metric-item">
              <span className="metric-label">Centroid Coordinates</span>
              <span className="metric-val metric-coords-text">
                {recommendedSite.latitude?.toFixed(4)}° N, {recommendedSite.longitude?.toFixed(4)}° E
              </span>
            </div>
          </div>

          {/* Recommended Site Pan Action */}
          <div>
            <button
              className="btn btn-outline btn-block btn-sm"
              type="button"
              onClick={() => handleFocus(recommendedSite)}
              title="Pan map view to recommended pond site"
            >
              🎯 Focus on Recommended Site
            </button>
          </div>

          {/* Collapsible Alternative Sites List */}
          {hasAlternatives && (
            <div className="alternatives-section">
              <button
                className="alternatives-toggle-btn"
                type="button"
                onClick={() => setIsAlternativesOpen((prev) => !prev)}
                aria-expanded={isAlternativesOpen}
              >
                <div className="alternatives-toggle-title">
                  <span>Alternative Candidate Locations</span>
                  <span className="alternatives-count-badge">{alternativeSites.length}</span>
                </div>
                <span>{isAlternativesOpen ? '▲ Hide' : '▼ View'}</span>
              </button>

              {isAlternativesOpen && (
                <div className="alternatives-list">
                  {alternativeSites.map((site) => {
                    const altTier = getScoreTier(site.suitability_score);
                    return (
                      <div key={site.site_id || `alt-${site.rank}`} className="alt-site-card">
                        <div className="alt-site-header">
                          <div className="alt-site-title">
                            <span>📍 Candidate #{site.rank}</span>
                            <span className="alt-site-subid">({site.site_id})</span>
                          </div>
                          <span className={`score-tier-badge ${altTier.tierClass}`}>
                            {site.suitability_score} / 100
                          </span>
                        </div>

                        <div className="alt-site-metrics-row">
                          <span>Area: <strong>{site.area_m2?.toLocaleString()} m²</strong></span>
                          {site.storage_capacity_m3 ? (
                            <span>Vol: <strong>{site.storage_capacity_m3?.toLocaleString()} m³</strong></span>
                          ) : null}
                          <span>Slope: <strong>{site.slope_deg?.toFixed(1)}°</strong></span>
                        </div>

                        <div className="alt-site-actions">
                          <button
                            className="btn-show-map"
                            type="button"
                            onClick={() => handleFocus(site)}
                            title={`Pan map to candidate site #${site.rank}`}
                          >
                            🎯 Show on Map
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
