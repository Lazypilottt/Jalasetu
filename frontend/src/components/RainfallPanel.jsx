import React, { useState } from 'react';
import { getRainfallData } from '../api/catchmentApi';

/**
 * Rainfall & Precipitation Analytics Panel
 *
 * Visualizes location-specific rainfall regime:
 * - Annual mean precipitation & monsoon share
 * - 24-hr design storm for SCS-CN runoff
 * - Interactive monthly precipitation distribution chart
 * - Multi-year historical comparison
 */
export default function RainfallPanel({
  rainfall = null,
  onApplyDesignRainfall = null,
  defaultLat = 21.26,
  defaultLon = 81.28,
}) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [customLat, setCustomLat] = useState(defaultLat);
  const [customLon, setCustomLon] = useState(defaultLon);
  const [liveRainfall, setLiveRainfall] = useState(null);
  const [isFetching, setIsFetching] = useState(false);
  const [fetchError, setFetchError] = useState(null);

  const activeData = liveRainfall || rainfall;

  const handleFetchCustom = async (e) => {
    e?.preventDefault();
    setIsFetching(true);
    setFetchError(null);
    try {
      const data = await getRainfallData(Number(customLat), Number(customLon));
      setLiveRainfall(data);
    } catch (err) {
      setFetchError(err.message || 'Failed to fetch rainfall for coordinates');
    } finally {
      setIsFetching(false);
    }
  };

  const monthlyData = activeData?.monthly_averages_mm || [];
  const maxMonthly = Math.max(...monthlyData.map((m) => m.rainfall_mm || 0), 100);

  return (
    <div className="rainfall-panel card" role="region" aria-label="Rainfall and Precipitation Analytics">
      <div className="panel-header" onClick={() => setIsExpanded((prev) => !prev)}>
        <div className="panel-title-group">
          <span className="panel-badge-icon" aria-hidden="true">🌧️</span>
          <div>
            <h3 className="panel-title">Precipitation & Monsoon Regime</h3>
            <span className="panel-subtitle">
              {activeData ? `${activeData.source || 'ERA5 Reanalysis'}` : 'Open-Meteo Climatology'}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="btn-toggle-panel"
          aria-label={isExpanded ? 'Collapse panel' : 'Expand panel'}
        >
          {isExpanded ? '−' : '+'}
        </button>
      </div>

      {isExpanded && (
        <div className="panel-content">
          {activeData ? (
            <>
              {/* Primary Key Metrics Grid */}
              <div className="rainfall-metrics-grid">
                <div className="metric-box">
                  <span className="metric-label">Mean Annual Rain</span>
                  <span className="metric-value-primary">
                    {Math.round(activeData.mean_annual_rainfall_mm).toLocaleString()}
                    <span className="metric-unit"> mm/yr</span>
                  </span>
                  <span className="metric-subtext">3-yr reanalysis average</span>
                </div>

                <div className="metric-box">
                  <span className="metric-label">Monsoon Precipitation</span>
                  <span className="metric-value-accent">
                    {Math.round(activeData.monsoon_rainfall_mm).toLocaleString()}
                    <span className="metric-unit"> mm</span>
                  </span>
                  <span className="metric-subtext">
                    {activeData.monsoon_share_pct ? `${activeData.monsoon_share_pct}% of total rain` : 'Jun – Sep peak'}
                  </span>
                </div>

                <div className="metric-box">
                  <span className="metric-label">24-hr Design Storm</span>
                  <span className="metric-value-highlight">
                    {Math.round(activeData.design_24h_rainfall_mm)}
                    <span className="metric-unit"> mm</span>
                  </span>
                  <span className="metric-subtext">Hydrological storm event</span>
                </div>
              </div>

              {/* Monthly Bar Chart Visualizer */}
              {monthlyData.length > 0 && (
                <div className="monthly-chart-container">
                  <div className="chart-header">
                    <span className="chart-title">Monthly Rainfall Distribution</span>
                    <span className="chart-legend-tag">
                      <span className="monsoon-indicator"></span> Monsoon (Jun-Sep)
                    </span>
                  </div>
                  <div className="monthly-bar-track">
                    {monthlyData.map((m) => {
                      const isMonsoon = [6, 7, 8, 9].includes(m.month_idx);
                      const barHeightPct = Math.round((m.rainfall_mm / maxMonthly) * 100);
                      return (
                        <div key={m.month_idx} className="month-col" title={`${m.month}: ${m.rainfall_mm} mm`}>
                          <div className="bar-wrapper">
                            <span className="bar-val-tooltip">{Math.round(m.rainfall_mm)}</span>
                            <div
                              className={`bar-fill ${isMonsoon ? 'bar-monsoon' : 'bar-dry'}`}
                              style={{ height: `${Math.max(4, barHeightPct)}%` }}
                            ></div>
                          </div>
                          <span className={`month-label ${isMonsoon ? 'month-monsoon' : ''}`}>{m.month}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Historical Year Breakdown */}
              {activeData.historical_annual && activeData.historical_annual.length > 0 && (
                <div className="historical-annual-row">
                  <span className="historical-title">Recent Years:</span>
                  <div className="historical-badges">
                    {activeData.historical_annual.map((yr) => (
                      <span key={yr.year} className="historical-badge">
                        <strong>{yr.year}:</strong> {Math.round(yr.rainfall_mm)} mm
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Hydrological Guidance Note */}
              {activeData.hydrological_notes && (
                <div className="hydrological-note-box">
                  <span className="note-icon">ℹ️</span>
                  <span>{activeData.hydrological_notes}</span>
                </div>
              )}

              {/* Apply Design Storm Button */}
              {typeof onApplyDesignRainfall === 'function' && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm btn-block mt-2"
                  onClick={() => onApplyDesignRainfall(activeData.design_24h_rainfall_mm)}
                  title="Apply this location's design storm to runoff calculations"
                >
                  ⚡ Use {Math.round(activeData.design_24h_rainfall_mm)} mm as Design Storm
                </button>
              )}
            </>
          ) : (
            <div className="rainfall-empty-state">
              <p>Upload a contour map to automatically retrieve location rainfall, or query coordinates below:</p>
            </div>
          )}

          {/* Coordinate Query Widget */}
          <form className="rainfall-custom-query" onSubmit={handleFetchCustom}>
            <span className="custom-query-title">Query Custom Coordinates</span>
            <div className="query-inputs-row">
              <label>
                Lat
                <input
                  type="number"
                  step="0.0001"
                  value={customLat}
                  onChange={(e) => setCustomLat(e.target.value)}
                  placeholder="e.g. 21.26"
                  required
                />
              </label>
              <label>
                Lon
                <input
                  type="number"
                  step="0.0001"
                  value={customLon}
                  onChange={(e) => setCustomLon(e.target.value)}
                  placeholder="e.g. 81.28"
                  required
                />
              </label>
              <button type="submit" className="btn btn-primary btn-sm" disabled={isFetching}>
                {isFetching ? 'Fetching...' : 'Query'}
              </button>
            </div>
            {fetchError && <span className="query-error-msg">{fetchError}</span>}
          </form>
        </div>
      )}
    </div>
  );
}
