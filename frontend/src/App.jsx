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
import HelpGuide from './components/HelpGuide';
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
const TABS = [
  { id: 'plan', label: 'Plan' },
  { id: 'results', label: 'Results' },
  { id: 'more', label: 'More' },
];
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
  const [tab, setTab] = useState('plan');
  const [guideOpen, setGuideOpen] = useState(() => !readFlag('jalasetu.guideSeen', false));
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

  const closeGuide = useCallback(() => {
    setGuideOpen(false);
    writeFlag('jalasetu.guideSeen', true);
  }, []);

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

  const requestAnalysis = () => {
    setAnalysisError(null);
    setAnalysisRequestToken((token) => token + 1);
  };

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
    setTab('results');
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
  const canRun = Boolean(selectedArea || uploadedFile) && settingsErrors.length === 0 && !isLoading;
  const actionLabel = isLoading
    ? 'Analysing…'
    : selectedArea
      ? 'Recommend a site here'
      : uploadedFile ? 'Analyse uploaded contours' : 'Pick a point on the map';
  const actionHint = settingsErrors.length
    ? settingsErrors[0]
    : selectedArea
      ? `${selectedArea.latitude.toFixed(5)}, ${selectedArea.longitude.toFixed(5)} · ${selectedArea.radiusM} m radius · ${terrainPlan?.label || ''}`
      : uploadedFile
        ? `Contours: ${uploadedFile.name}. Click the map to focus on one spot.`
        : 'Click anywhere on the map, search a village, or use your location.';

  const hasResult = Boolean(analysisResult);

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
            <p className="brand-tagline">Find the right spot for a farm pond</p>
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
          <button type="button" className="header-btn" onClick={() => setGuideOpen(true)} aria-haspopup="dialog">
            <span aria-hidden="true">?</span>
            <span className="header-btn-label">Guide</span>
          </button>
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
          {/* Pinned: where, the one main action, and live progress */}
          <div className={`action-bar ${isLoading ? 'running' : ''}`}>
            <div className="action-bar-top">
              <span className={`action-bar-dot ${selectedArea ? 'on' : ''}`} aria-hidden="true" />
              <div className="action-bar-text">
                <strong>{selectedArea ? 'Point selected' : uploadedFile ? 'Contour map loaded' : 'Start here'}</strong>
                <span className={settingsErrors.length ? 'action-bar-error' : ''}>{actionHint}</span>
              </div>
              {selectedArea && !isLoading && (
                <button type="button" className="icon-btn" onClick={handleAreaClear} aria-label="Clear selected point" title="Clear point">
                  ✕
                </button>
              )}
            </div>
            <button
              type="button"
              className="btn btn-primary btn-block action-bar-btn"
              onClick={requestAnalysis}
              disabled={!canRun}
            >
              {isLoading && <span className="loading-spinner-sm" aria-hidden="true" />}
              {actionLabel}
            </button>
            {isLoading && (
              <PipelineProgress progress={progress && { ...progress, skipStages: settings.avoid_infrastructure ? [] : ['infrastructure'] }} />
            )}
            {analysisError && !isLoading && (
              <div className="action-bar-alert" role="alert">
                <strong>Could not finish the analysis.</strong> {analysisError.message}
              </div>
            )}
          </div>

          <div className="sidebar-tabs" role="tablist" aria-label="Side panel sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`tab-${t.id}`}
                aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`}
                className={`sidebar-tab ${tab === t.id ? 'active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {t.id === 'results' && hasResult && tab !== 'results' && <span className="sidebar-tab-dot" aria-label="new results" />}
              </button>
            ))}
          </div>

          {/* Tabs stay mounted so an analysis keeps running while you switch. */}
          <div className="sidebar-panel" role="tabpanel" id="panel-plan" aria-labelledby="tab-plan" hidden={tab !== 'plan'}>
            {!selectedArea && !uploadedFile && !hasResult && (
              <div className="welcome-intro-card" role="region" aria-label="About JalaSetu">
                <div className="welcome-header">
                  <span className="welcome-icon" aria-hidden="true">i</span>
                  <h3 className="welcome-title">New here?</h3>
                </div>
                <p className="welcome-text">
                  Pick any point on the map and JalaSetu suggests where a farm pond should go, keeps clear of rivers,
                  homes, schools and roads, and estimates how much rainwater it can collect.
                </p>
                <button type="button" className="btn btn-outline btn-sm" onClick={() => setGuideOpen(true)}>
                  Read the 1-minute guide
                </button>
              </div>
            )}

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

            <AnalysisSettings settings={settings} onChange={setSettings} disabled={isLoading} />

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
              loadingContent={<p className="upload-running-note">Analysis running — progress is shown at the top.</p>}
              params={analysisParams}
            />
          </div>

          <div className="sidebar-panel" role="tabpanel" id="panel-results" aria-labelledby="tab-results" hidden={tab !== 'results'}>
            {!hasResult && (
              <div className="empty-state">
                <span className="empty-state-icon" aria-hidden="true">◎</span>
                <h3>No recommendation yet</h3>
                <p>
                  {selectedArea
                    ? 'Press “Recommend a site here” above. Results appear here when the analysis finishes.'
                    : 'Pick a point on the map first, then press “Recommend a site here”.'}
                </p>
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

          </div>

          <div className="sidebar-panel" role="tabpanel" id="panel-more" aria-labelledby="tab-more" hidden={tab !== 'more'}>
            <HistoryPanel
              entries={history}
              onRestore={(entry) => {
                handleRestore(entry);
                setTab('plan');
              }}
              onClear={() => setHistory(clearHistory())}
              disabled={isLoading}
            />
            {history.length === 0 && (
              <div className="empty-state empty-state-compact">
                <h3>No recent analyses</h3>
                <p>Finished recommendations are kept here in this browser so you can reopen them.</p>
              </div>
            )}
            <ClusterPanel cluster={cluster} activeProgress={isLoading ? progress : null} />
            <div className="about-card">
              <strong>Data &amp; licences</strong>
              <p>All maps and data come from free, open services that need no API key.</p>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setGuideOpen(true)}>
                See sources in the guide
              </button>
            </div>
          </div>
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

      <HelpGuide isOpen={guideOpen} onClose={closeGuide} />
    </div>
  );
}
