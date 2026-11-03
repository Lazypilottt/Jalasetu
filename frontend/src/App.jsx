import React, { useCallback, useEffect, useMemo, useState } from 'react';
import UploadPanel from './components/UploadPanel';
import MapView from './components/MapView';
import SiteSummaryPanel from './components/SiteSummaryPanel';
import CatchmentDetailsPanel from './components/CatchmentDetailsPanel';
import ProcessingNotesBanner from './components/ProcessingNotesBanner';
import RainfallPanel from './components/RainfallPanel';
import AnalysisSettings from './components/AnalysisSettings';
import SiteConstraintsPanel, { surveyRadiusFor } from './components/SiteConstraintsPanel';
import PipelineProgress from './components/PipelineProgress';
import ClusterPanel from './components/ClusterPanel';
import ResultsToolbar from './components/ResultsToolbar';
import HistoryPanel from './components/HistoryPanel';
import { getInfrastructure, runAnalysis } from './api/catchmentApi';
import useClusterStatus from './hooks/useClusterStatus';
import useTheme from './hooks/useTheme';
import { loadSettings, saveSettings, settingsToParams, terrainPlanFor, validateSettings } from './utils/settings';
import { addHistoryEntry, clearHistory, loadHistory, summarizeResult } from './utils/history';
import { readSelectionFromHash, writeSelectionToHash } from './utils/urlState';

function initialSelection() {
  try {
    const shared = readSelectionFromHash();
    return shared ? { latitude: shared.latitude, longitude: shared.longitude } : null;
  } catch {
    return null;
  }
}

function initialSettings() {
  const settings = loadSettings();
  try {
    const shared = readSelectionFromHash();
    if (shared?.radiusM) settings.radiusM = shared.radiusM;
  } catch {
    // ignore malformed hash
  }
  return settings;
}

function readFlag(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value === 'true';
  } catch {
    return fallback;
  }
}

function writeFlag(key, value) {
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    // convenience only
  }
}

const THEME_ICONS = { system: '◐', light: '☀', dark: '☾' };
const SAME_POINT_EPS = 0.000001;

/**
 * Main JalaSetu application.
 *
 * Coordinates end-to-end user workflows:
 *  - Click anywhere (or search) to pick a site; contours are used where they exist,
 *    a global DEM elsewhere, and existing infrastructure is kept out of the siting
 *  - Upload, analysis settings, site constraints, shareable selection, history
 *  - Live pipeline progress and per-node cluster capacity
 *  - Theme (system / light / dark) and map synchronisation
 */
export default function App() {
  const [uploadedFile, setUploadedFile] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [focusedSite, setFocusedSite] = useState(null);
  const [selection, setSelection] = useState(initialSelection);
  const [settings, setSettings] = useState(initialSettings);
  const [progress, setProgress] = useState(null);
  const [history, setHistory] = useState(loadHistory);
  const [analysisRequestToken, setAnalysisRequestToken] = useState(0);
  const [manualZones, setManualZones] = useState([]);
  const [clickMode, setClickMode] = useState('select');
  const [zoneRadius, setZoneRadius] = useState(25);
  const [autoRecommend, setAutoRecommend] = useState(() => readFlag('jalasetu.autoRecommend', false));
  const [infraPreview, setInfraPreview] = useState({ loading: false, data: null, error: null });
  const cluster = useClusterStatus({ active: isLoading });
  const theme = useTheme();

  const settingsErrors = validateSettings(settings);
  const selectedArea = useMemo(
    () => (selection ? { ...selection, radiusM: settings.radiusM } : null),
    [selection, settings.radiusM]
  );
  const terrainPlan = terrainPlanFor(settings, uploadedFile, selectedArea);

  useEffect(() => saveSettings(settings), [settings]);
  useEffect(() => writeSelectionToHash(selectedArea), [selectedArea]);
  useEffect(() => writeFlag('jalasetu.autoRecommend', autoRecommend), [autoRecommend]);

  // Preview mapped infrastructure around the selected point before analysis.
  const previewKey = selectedArea && settings.avoid_infrastructure
    ? `${selectedArea.latitude.toFixed(5)},${selectedArea.longitude.toFixed(5)},${Math.round(surveyRadiusFor(selectedArea.radiusM))}`
    : null;
  useEffect(() => {
    if (!previewKey) {
      setInfraPreview({ loading: false, data: null, error: null });
      return undefined;
    }
    const [lat, lon, radius] = previewKey.split(',').map(Number);
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setInfraPreview((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const data = await getInfrastructure(lat, lon, radius, { signal: controller.signal });
        if (!controller.signal.aborted) setInfraPreview({ loading: false, data, error: null });
      } catch (err) {
        if (!controller.signal.aborted) {
          // The single-node FastAPI app without this route, or a network error.
          setInfraPreview({ loading: false, data: null, error: err.status === 404 ? null : err.message });
        }
      }
    }, 800);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [previewKey]);

  const resetResults = () => {
    setAnalysisResult(null);
    setAnalysisError(null);
    setFocusedSite(null);
    setProgress(null);
  };

  const handleFileSelect = (file) => {
    setUploadedFile(file);
    resetResults();
  };

  const handleFileClear = () => {
    setUploadedFile(null);
    resetResults();
    setIsLoading(false);
  };

  const requestAnalysis = () => setAnalysisRequestToken((token) => token + 1);

  const handleAreaSelect = ({ latitude, longitude }) => {
    setSelection({ latitude, longitude });
    if (autoRecommend && !isLoading && settingsErrors.length === 0) requestAnalysis();
  };

  const handleAreaClear = () => {
    setSelection(null);
    setFocusedSite(null);
  };

  const handleAddZone = ({ lat, lon }) => {
    setManualZones((zones) => [
      ...zones,
      { id: `${Date.now()}-${zones.length}`, lat, lon, radius_m: zoneRadius, label: `Marked zone ${zones.length + 1}` },
    ]);
  };

  const analyze = useCallback(
    (file, params) => {
      setProgress(null);
      return runAnalysis(file, params, { onProgress: setProgress });
    },
    []
  );

  const handleAnalysisComplete = (response) => {
    setAnalysisResult(response);
    setAnalysisError(null);
    setFocusedSite(null);
    setIsLoading(false);
    setClickMode('select');
    setHistory(addHistoryEntry(summarizeResult(response, { fileName: uploadedFile?.name, settings, selectedArea })));
  };

  const handleAnalysisError = (err) => {
    setAnalysisError(err);
    setIsLoading(false);
  };

  const handleRestore = (entry) => {
    if (entry.settings) setSettings({ ...settings, ...entry.settings });
    if (entry.area) setSelection({ latitude: entry.area.latitude, longitude: entry.area.longitude });
    resetResults();
  };

  const analysisParams = {
    ...settingsToParams(settings),
    ...(selectedArea
      ? {
          selected_latitude: selectedArea.latitude,
          selected_longitude: selectedArea.longitude,
          selected_radius_m: selectedArea.radiusM,
        }
      : {}),
    ...(manualZones.length
      ? { manual_exclusions: JSON.stringify(manualZones.map(({ lat, lon, radius_m, label }) => ({ lat, lon, radius_m, label }))) }
      : {}),
  };

  // The result's own infrastructure is shown once it is for the current point.
  const resultMatchesSelection = Boolean(
    analysisResult?.selected_area && selectedArea &&
      Math.abs(analysisResult.selected_area.latitude - selectedArea.latitude) < SAME_POINT_EPS &&
      Math.abs(analysisResult.selected_area.longitude - selectedArea.longitude) < SAME_POINT_EPS
  );
  const mapInfrastructure = resultMatchesSelection && analysisResult?.infrastructure?.features_geojson
    ? analysisResult.infrastructure.features_geojson
    : infraPreview.data?.status === 'ok' ? infraPreview.data.features : null;
  const mapZones = resultMatchesSelection ? analysisResult?.infrastructure?.zones_geojson : null;

  const getHeaderStatus = () => {
    if (isLoading) return { dotClass: 'status-dot status-dot-loading', label: 'Analyzing terrain…', badgeClass: 'badge-header-loading' };
    if (analysisError) return { dotClass: 'status-dot status-dot-error', label: 'Analysis failed', badgeClass: 'badge-header-error' };
    if (analysisResult && selectedArea) {
      const analyzed = analysisResult.selected_area;
      const changed = !analyzed || !resultMatchesSelection || Math.abs(Number(analyzed.radius_m) - selectedArea.radiusM) > 0.5;
      if (changed) return { dotClass: 'status-dot status-dot-ready', label: 'New point selected', badgeClass: 'badge-header-ready' };
    }
    if (analysisResult) return { dotClass: 'status-dot status-dot-success', label: 'Recommendation ready', badgeClass: 'badge-header-success' };
    if (uploadedFile || selectedArea) return { dotClass: 'status-dot status-dot-ready', label: 'Ready to analyze', badgeClass: 'badge-header-ready' };
    return { dotClass: 'status-dot', label: 'Click the map to begin', badgeClass: '' };
  };

  const headerStatus = getHeaderStatus();
  const clusterNodes = cluster.data?.nodes || [];
  const nodesUp = clusterNodes.filter((n) => n.reachable !== false).length;
  const analyzeLabel = terrainPlan?.id === 'global'
    ? 'Recommend a site here · global DEM'
    : uploadedFile ? 'Recommend a site in this area' : 'Recommend a site here · demo contours';

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="brand-section">
          <span className="brand-logo-icon" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="30" height="30">
              <defs>
                <linearGradient id="brandGradient" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#22d3ee" />
                  <stop offset="1" stopColor="#10b981" />
                </linearGradient>
              </defs>
              <path d="M16 3c5 6.5 9 11.2 9 16a9 9 0 0 1-18 0c0-4.8 4-9.5 9-16z" fill="url(#brandGradient)" />
              <path d="M10.5 20.5c1.6 1.3 3.4 2 5.5 2s3.9-.7 5.5-2" stroke="#ffffff" strokeWidth="1.6" fill="none" strokeLinecap="round" opacity="0.85" />
            </svg>
          </span>
          <div>
            <h1 className="brand-title">JalaSetu</h1>
            <p className="brand-tagline">Farm-pond siting console · terrain, hydrology &amp; infrastructure-aware</p>
          </div>
        </div>

        <div className="header-status-group">
          {cluster.mode === 'distributed' && (
            <span
              className={`header-cluster-chip ${nodesUp === clusterNodes.length ? '' : 'header-cluster-chip-degraded'}`}
              title="Cluster nodes reachable from the gateway"
            >
              {nodesUp}/{clusterNodes.length} nodes
            </span>
          )}
          <div className={`header-status-badge ${headerStatus.badgeClass}`} role="status" aria-live="polite">
            <span className={headerStatus.dotClass}></span>
            <span>{headerStatus.label}</span>
          </div>
          <button
            type="button"
            className="theme-toggle"
            onClick={theme.cycle}
            title={`Theme: ${theme.mode} (click to change)`}
            aria-label={`Theme: ${theme.mode}. Click to change.`}
          >
            <span aria-hidden="true">{THEME_ICONS[theme.mode]}</span>
            <span className="theme-toggle-label">{theme.mode}</span>
          </button>
        </div>
      </header>

      <div className="main-layout">
        <aside className="sidebar-area" aria-label="Control and Analysis Panels">
          <UploadPanel
            onAnalysisComplete={handleAnalysisComplete}
            onFileSelect={handleFileSelect}
            onFileClear={handleFileClear}
            onLoadingChange={setIsLoading}
            onError={handleAnalysisError}
            analyzeContourFn={analyze}
            analysisRequestToken={analysisRequestToken}
            allowDefaultContour
            canAnalyze={settingsErrors.length === 0}
            loadingContent={
              <PipelineProgress progress={progress && { ...progress, skipStages: settings.avoid_infrastructure ? [] : ['infrastructure'] }} />
            }
            params={analysisParams}
          />

          <div className="selection-help-card" role="status">
            <div className="selection-help-header">
              <strong>{selectedArea ? 'Point selected' : 'Pick a point'}</strong>
              {selectedArea && (
                <button
                  className="btn btn-ghost btn-sm selection-clear-btn"
                  type="button"
                  onClick={handleAreaClear}
                  disabled={isLoading}
                  aria-label="Clear selected point"
                >
                  Clear
                </button>
              )}
            </div>
            <span>
              {selectedArea
                ? `${selectedArea.latitude.toFixed(5)}, ${selectedArea.longitude.toFixed(5)} · ${selectedArea.radiusM} m search radius.`
                : 'Click anywhere on the map, search a village, or use your location. No contour file is needed.'}
            </span>
            {selectedArea && (
              <button
                className="btn btn-primary btn-sm btn-block selection-analyze-btn"
                type="button"
                onClick={requestAnalysis}
                disabled={isLoading || settingsErrors.length > 0}
              >
                {analyzeLabel}
              </button>
            )}
          </div>

          <AnalysisSettings settings={settings} onChange={setSettings} disabled={isLoading} />

          <SiteConstraintsPanel
            settings={settings}
            onSettingsChange={setSettings}
            selectedArea={selectedArea}
            preview={infraPreview}
            terrainPlan={terrainPlan}
            manualZones={manualZones}
            onRemoveZone={(id) => setManualZones((zones) => zones.filter((z) => z.id !== id))}
            onClearZones={() => setManualZones([])}
            markMode={clickMode === 'zone'}
            onToggleMarkMode={() => setClickMode((mode) => (mode === 'zone' ? 'select' : 'zone'))}
            zoneRadius={zoneRadius}
            onZoneRadiusChange={setZoneRadius}
            disabled={isLoading}
          />

          {!analysisResult && !uploadedFile && !isLoading && !selectedArea && (
            <div className="welcome-intro-card" role="region" aria-label="About JalaSetu">
              <div className="welcome-header">
                <span className="welcome-icon" aria-hidden="true">i</span>
                <h3 className="welcome-title">Village Pond Siting Assistant</h3>
              </div>
              <p className="welcome-text">
                JalaSetu finds natural low-lying depressions, keeps clear of rivers, tanks, homes, schools and roads,
                and estimates the rainwater each pond can collect.
              </p>
              <div className="welcome-steps">
                <div className="welcome-step-item">
                  <span className="step-num">1</span>
                  <span>Click any point on the map (or search a village). Upload a .kml/.kmz contour map for survey-grade terrain.</span>
                </div>
                <div className="welcome-step-item">
                  <span className="step-num">2</span>
                  <span>Review the infrastructure that will be avoided, and mark wells or other no-build zones.</span>
                </div>
                <div className="welcome-step-item">
                  <span className="step-num">3</span>
                  <span>Recommend a site, compare alternatives, and export GeoJSON or CSV.</span>
                </div>
              </div>
            </div>
          )}

          <ResultsToolbar result={analysisResult} selectedArea={selectedArea} />

          <ProcessingNotesBanner
            status={analysisResult?.status}
            notes={analysisResult?.processing_notes}
            response={analysisResult}
          />

          <SiteSummaryPanel
            recommendedSite={analysisResult?.recommended_site}
            alternativeSites={analysisResult?.alternative_sites}
            onSelectSite={setFocusedSite}
            onPanToSite={setFocusedSite}
          />

          <CatchmentDetailsPanel catchment={analysisResult?.catchment} />

          <RainfallPanel
            rainfall={resultMatchesSelection ? analysisResult?.rainfall : null}
            followPoint={selectedArea}
            onApplyDesignRainfall={(val) => {
              setSettings((current) => ({ ...current, design_rainfall_mm: val }));
              requestAnalysis();
            }}
            defaultLat={selectedArea?.latitude || analysisResult?.recommended_site?.latitude || 21.26}
            defaultLon={selectedArea?.longitude || analysisResult?.recommended_site?.longitude || 81.28}
          />

          <ClusterPanel cluster={cluster} activeProgress={isLoading ? progress : null} />

          <HistoryPanel
            entries={history}
            onRestore={handleRestore}
            onClear={() => setHistory(clearHistory())}
            disabled={isLoading}
          />
        </aside>

        <main className="map-area" aria-label="Interactive GIS Map View">
          <MapView
            analysisData={analysisResult}
            focusedSite={focusedSite}
            selectedArea={selectedArea}
            selectionRadiusM={settings.radiusM}
            onAreaSelect={handleAreaSelect}
            theme={theme.resolved}
            clickMode={clickMode}
            onAddZone={handleAddZone}
            manualZones={manualZones}
            infrastructureFeatures={mapInfrastructure}
            exclusionZones={mapZones}
            isAnalyzing={isLoading}
            onRecommendHere={requestAnalysis}
            autoRecommend={autoRecommend}
            onToggleAutoRecommend={() => setAutoRecommend((v) => !v)}
          />
        </main>
      </div>
    </div>
  );
}
