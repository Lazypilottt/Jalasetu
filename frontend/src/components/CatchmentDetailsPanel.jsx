import React from 'react';

/**
 * Translates the hydrological routing delineation method into plain-language
 * copy and trust/reliability level for village administration.
 *
 * @param {string} method - 'flow_accumulation' or 'basin_approximation'.
 * @returns {{ label: string, trustBadge: string, bannerClass: string, badgeClass: string, icon: string, description: string, advice: string }}
 */
export function getMethodTrustMetadata(method) {
  if (method === 'flow_accumulation') {
    return {
      label: 'Full terrain flow analysis',
      trustBadge: 'High Precision',
      bannerClass: 'trust-banner-high',
      badgeClass: 'badge-trust-high',
      icon: '🌊',
      description:
        'Continuous terrain flow routing model. Traces physical rainwater paths from surrounding ridges down to the pond excavation site.',
      advice: 'Reliable for volumetric pond capacity planning and watershed civil engineering calculations.',
    };
  }

  return {
    label: 'Simplified estimate — for detailed planning, verify on-site',
    trustBadge: 'Simplified Estimate',
    bannerClass: 'trust-banner-approx',
    badgeClass: 'badge-trust-approx',
    icon: '⚠️',
    description:
      'Topographic basin approximation. Estimates uphill drainage area using local elevation gradients.',
    advice:
      'Provides a helpful preliminary guide. Ground verification and on-site hydrological assessment are recommended before civil excavation.',
  };
}

/**
 * CatchmentDetailsPanel Component
 *
 * Displays the upstream contributing catchment drainage area, mean basin slope,
 * elevation relief span, and clearly surfaces the hydrological delineation method
 * to communicate the reliability/trust level of the calculation to the user.
 *
 * @param {Object} props
 * @param {Object|null} [props.catchment] - CatchmentSummary object.
 */
export default function CatchmentDetailsPanel({ catchment = null }) {
  // Graceful empty state before file upload / analysis
  if (!catchment) {
    return (
      <div className="panel catchment-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <span className="panel-icon">🌊</span>
            <h3 className="panel-title">Catchment Hydrology</h3>
          </div>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <span className="empty-state-icon">🌊</span>
            <p className="empty-state-text">
              Upstream watershed boundary and runoff drainage metrics will appear here once contour analysis is complete.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const methodMeta = getMethodTrustMetadata(catchment.delineation_method);
  const relief = catchment.elevation_range_m?.relief_m ?? (
    (catchment.elevation_range_m?.max_m || 0) - (catchment.elevation_range_m?.min_m || 0)
  );

  const hasHydrology = catchment.estimated_runoff_volume_m3 !== undefined && catchment.estimated_runoff_volume_m3 !== null;
  const hasFeasibility = !!catchment.hydrological_feasibility;
  const hasSiltation = !!catchment.siltation_risk;

  const getFeasibilityBadge = (status) => {
    if (status === 'optimal') {
      return { label: 'Optimal Sizing', badgeClass: 'badge-trust-high', icon: '✅' };
    }
    if (status === 'low_yield_risk') {
      return { label: 'Low Runoff Risk', badgeClass: 'badge-trust-approx', icon: '⚠️' };
    }
    if (status === 'high_flow_excess') {
      return { label: 'Spillway Required', badgeClass: 'badge-trust-approx', icon: '🌊' };
    }
    return { label: 'Evaluated', badgeClass: 'badge-trust-high', icon: '💧' };
  };

  const getSiltationBadge = (risk) => {
    if (risk === 'low') return { label: 'Low Siltation Risk', badgeClass: 'badge-trust-high', icon: '🛡️' };
    if (risk === 'moderate') return { label: 'Moderate Siltation Risk', badgeClass: 'badge-trust-approx', icon: '⚠️' };
    return { label: 'High Siltation Risk', badgeClass: 'score-tier-marginal', icon: '🚨' };
  };

  const feasBadge = getFeasibilityBadge(catchment.hydrological_feasibility);
  const siltBadge = getSiltationBadge(catchment.siltation_risk);

  return (
    <div className="panel catchment-panel">
      {/* Panel Header */}
      <div className="panel-header">
        <div className="panel-title-group">
          <span className="panel-icon">🌊</span>
          <h3 className="panel-title">Catchment Hydrology</h3>
        </div>
        <span className={`badge ${methodMeta.badgeClass}`}>{methodMeta.trustBadge}</span>
      </div>

      {/* Panel Body */}
      <div className="panel-body">
        <div className="catchment-metrics-card">
          {/* Hero Contributing Catchment Area Banner */}
          <div className="catchment-hero-card">
            <div className="catchment-hero-left">
              <span className="catchment-hero-label">Contributing Drainage Area</span>
              <span className="catchment-hero-val">{catchment.area_hectares?.toFixed(2)} ha</span>
              <span className="catchment-hero-sub">
                {catchment.area_m2?.toLocaleString()} m² of natural runoff watershed
              </span>
            </div>
            <div className="hero-water-drop-icon">💧</div>
          </div>

          {/* Key Hydrological Metrics Grid */}
          <div className="metrics-grid">
            <div className="metric-item">
              <span className="metric-label">Mean Basin Slope</span>
              <span className="metric-val">{catchment.average_slope_deg?.toFixed(1)}°</span>
            </div>

            <div className="metric-item">
              <span className="metric-label">Elevation Relief Span</span>
              <span className="metric-val">{relief.toFixed(1)} m</span>
            </div>

            <div className="metric-item">
              <span className="metric-label">Lowest Elevation (Pond)</span>
              <span className="metric-val">{catchment.elevation_range_m?.min_m?.toFixed(1)} m</span>
            </div>

            <div className="metric-item">
              <span className="metric-label">Highest Basin Ridge</span>
              <span className="metric-val">{catchment.elevation_range_m?.max_m?.toFixed(1)} m</span>
            </div>

            {hasHydrology && (
              <div className="metric-item">
                <span className="metric-label">SCS Storm Runoff Volume</span>
                <span className="metric-val" title={`Under ${catchment.design_rainfall_mm || 100}mm storm (CN=${catchment.curve_number || 75})`}>
                  {catchment.estimated_runoff_volume_m3?.toLocaleString()} m³
                </span>
              </div>
            )}

            {catchment.catchment_to_pond_ratio !== undefined && catchment.catchment_to_pond_ratio !== null && (
              <div className="metric-item">
                <span className="metric-label">Catchment / Pond Ratio</span>
                <span className="metric-val" title="Recommended optimal ratio is 10x - 50x">
                  {catchment.catchment_to_pond_ratio?.toFixed(1)}×
                </span>
              </div>
            )}
          </div>

          {/* Hydrological Sizing Feasibility Notice */}
          {hasFeasibility && (
            <div className="delineation-trust-banner trust-banner-high" style={{ marginTop: '0.75rem' }}>
              <div className="trust-banner-header">
                <div className="trust-title-group">
                  <span className="trust-icon">{feasBadge.icon}</span>
                  <span className="trust-label">Hydrological Feasibility</span>
                </div>
                <span className={feasBadge.badgeClass}>{feasBadge.label}</span>
              </div>
              <p className="trust-desc">{catchment.feasibility_explanation}</p>
            </div>
          )}

          {/* Siltation & Soil Erosion Risk Banner */}
          {hasSiltation && (
            <div className={`delineation-trust-banner ${catchment.siltation_risk === 'low' ? 'trust-banner-high' : 'trust-banner-approx'}`} style={{ marginTop: '0.75rem' }}>
              <div className="trust-banner-header">
                <div className="trust-title-group">
                  <span className="trust-icon">{siltBadge.icon}</span>
                  <span className="trust-label">RUSLE Siltation Risk (LS: {catchment.mean_ls_factor?.toFixed(1)})</span>
                </div>
                <span className={siltBadge.badgeClass}>{siltBadge.label}</span>
              </div>
              <p className="trust-desc">{catchment.siltation_explanation}</p>
            </div>
          )}

          {/* Delineation Method & Trust Level Banner */}
          <div className={`delineation-trust-banner ${methodMeta.bannerClass}`} role="region" aria-label="Method Reliability" style={{ marginTop: '0.75rem' }}>
            <div className="trust-banner-header">
              <div className="trust-title-group">
                <span className="trust-icon">{methodMeta.icon}</span>
                <span className="trust-label">{methodMeta.label}</span>
              </div>
              <span className={methodMeta.badgeClass}>{methodMeta.trustBadge}</span>
            </div>
            <p className="trust-desc">{methodMeta.description}</p>
            <p className="trust-advice">
              <strong>Planning Guidance:</strong> {methodMeta.advice}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
