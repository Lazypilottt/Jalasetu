import React, { useCallback, useEffect, useMemo, useState } from 'react';
import UploadPanel from './components/UploadPanel';
import MapView from './components/MapView';
import SiteSummaryPanel from './components/SiteSummaryPanel';
import CatchmentDetailsPanel from './components/CatchmentDetailsPanel';
import ProcessingNotesBanner from './components/ProcessingNotesBanner';
import RainfallPanel from './components/RainfallPanel';
import AnalysisSettings from './components/AnalysisSettings';
import PipelineProgress from './components/PipelineProgress';
import ClusterPanel from './components/ClusterPanel';
import ResultsToolbar from './components/ResultsToolbar';
import HistoryPanel from './components/HistoryPanel';
import { runAnalysis } from './api/catchmentApi';
import useClusterStatus from './hooks/useClusterStatus';
import { loadSettings, saveSettings, settingsToParams, validateSettings } from './utils/settings';
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

/**
 * Main Jalasetu Application Component
 *
 * Coordinates end-to-end user workflows:
 *  - File upload, client-side validation, and analysis through the distributed job queue
 *    (falls back to the synchronous FastAPI endpoint on a single-node backend)
 *  - Analysis settings, shareable map selection, and recent-analysis history
 *  - Live pipeline progress and per-node cluster capacity
 *  - Automatic map view synchronization and result layer rendering
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
  const cluster = useClusterStatus({ active: isLoading });

  const settingsErrors = validateSettings(settings);
  const selectedArea = useMemo(
    () => (selection ? { ...selection, radiusM: settings.radiusM } : null),
    [selection, settings.radiusM]
  );

  useEffect(() => saveSettings(settings), [settings]);
  useEffect(() => writeSelectionToHash(selectedArea), [selectedArea]);

  const resetResults = () => {
    setAnalysisResult(null);
    setAnalysisError(null);
    setFocusedSite(null);
    setProgress(null);
  };

  /**
   * Invoked when a new file is chosen or dropped in the UploadPanel.
   * Clears any previous analysis results; the selected area is kept.
   */
  const handleFileSelect = (file) => {
    setUploadedFile(file);
    resetResults();
  };

  const handleFileClear = () => {
    setUploadedFile(null);
    resetResults();
    setIsLoading(false);
  };

  const handleAreaSelect = ({ latitude, longitude }) => {
    setSelection({ latitude, longitude });
  };

  const handleAreaClear = () => {
    setSelection(null);
    setFocusedSite(null);
  };

  const requestAnalysis = () => setAnalysisRequestToken((token) => token + 1);

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
  };

  // Derive human-readable header status indicator
  const getHeaderStatus = () => {
    if (isLoading) {
      return { dotClass: 'status-dot status-dot-loading', label: 'Analyzing Terrain...', badgeClass: 'badge-header-loading' };
    }
    if (analysisError) {
      return { dotClass: 'status-dot status-dot-error', label: 'Analysis Failed', badgeClass: 'badge-header-error' };
    }
    if (analysisResult && selectedArea) {
      const analyzed = analysisResult.selected_area;
      const selectionChanged =
        !analyzed ||
        Math.abs(Number(analyzed.latitude) - selectedArea.latitude) > 0.000001 ||
        Math.abs(Number(analyzed.longitude) - selectedArea.longitude) > 0.000001 ||
        Math.abs(Number(analyzed.radius_m) - selectedArea.radiusM) > 0.5;
      if (selectionChanged) {
        return { dotClass: 'status-dot status-dot-ready', label: 'New Area Selected', badgeClass: 'badge-header-ready' };
      }
    }
    if (analysisResult) {
      return { dotClass: 'status-dot status-dot-success', label: 'Analysis Complete', badgeClass: 'badge-header-success' };
    }
    if (uploadedFile || selectedArea) {
      return { dotClass: 'status-dot status-dot-ready', label: 'Ready to Analyze', badgeClass: 'badge-header-ready' };
    }
    return { dotClass: 'status-dot', label: 'Select an area or upload contours', badgeClass: '' };
  };

  const headerStatus = getHeaderStatus();
  const clusterNodes = cluster.data?.nodes || [];
  const nodesUp = clusterNodes.filter((n) => n.reachable !== false).length;

  return (
    <div className="app-container">
      {/* Top Application Header */}
      <header className="app-header">
        <div className="brand-section">
          <span className="brand-logo-icon" aria-hidden="true">JS</span>
          <div>
            <h1 className="brand-title">JalaSetu</h1>
            <p className="brand-tagline">Smarter farm pond siting & catchment analysis for villages</p>
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
          {/* Dynamic Global Status Badge */}
          <div className={`header-status-badge ${headerStatus.badgeClass}`} role="status" aria-live="polite">
            <span className={headerStatus.dotClass}></span>
            <span>{headerStatus.label}</span>
          </div>
        </div>
      </header>

      {/* Main Split Layout: Sidebar Controls + Interactive GIS Map */}
      <div className="main-layout">
        {/* Left Sidebar Area for Controls and Result Panels */}
        <aside className="sidebar-area" aria-label="Control and Analysis Panels">
          {/* 1. Contour Map Upload Panel */}
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
            loadingContent={<PipelineProgress progress={progress} />}
            params={analysisParams}
          />

          {/* 2. Analysis settings: preset, radius, hydrology, MCDM weights */}
          <AnalysisSettings settings={settings} onChange={setSettings} disabled={isLoading} />

          <div className="selection-help-card" role="status">
            <div className="selection-help-header">
              <strong>{selectedArea ? 'Land area selected' : 'Select a land area'}</strong>
              {selectedArea && (
                <button
                  className="btn btn-ghost btn-sm selection-clear-btn"
                  type="button"
                  onClick={handleAreaClear}
                  disabled={isLoading}
                  aria-label="Clear selected land area"
                >
                  Clear
                </button>
              )}
            </div>
            <span>
              {selectedArea
                ? `${selectedArea.radiusM} m radius at ${selectedArea.latitude.toFixed(5)}, ${selectedArea.longitude.toFixed(5)}. Click Analyze to update the recommendation.`
                : `Click anywhere on the map to select a ${settings.radiusM} m analysis radius before running the analysis.`}
            </span>
            {selectedArea && (
              <button
                className="btn btn-primary btn-sm btn-block selection-analyze-btn"
                type="button"
                onClick={requestAnalysis}
                disabled={isLoading || settingsErrors.length > 0}
              >
                {uploadedFile ? 'Analyze selected area' : 'Analyze selected area (demo contours)'}
              </button>
            )}
          </div>

          {/* Welcome Intro Card (Shown on First Load / Landing State) */}
          {!analysisResult && !uploadedFile && !isLoading && (
            <div className="welcome-intro-card" role="region" aria-label="About Jalasetu">
              <div className="welcome-header">
                <span className="welcome-icon" aria-hidden="true">01</span>
                <h3 className="welcome-title">Village Pond Siting Assistant</h3>
              </div>
              <p className="welcome-text">
                Jalasetu analyzes topographic contour maps to identify natural low-lying depressions and calculate upstream rainwater catchment areas for optimal farm pond placement.
              </p>
              <div className="welcome-steps">
                <div className="welcome-step-item">
                  <span className="step-num">1</span>
                  <span>Upload a contour map (.kml or .kmz), or click the map to try the bundled demo contours.</span>
                </div>
                <div className="welcome-step-item">
                  <span className="step-num">2</span>
                  <span>Tune the radius, land cover and design storm in Analysis settings.</span>
                </div>
                <div className="welcome-step-item">
                  <span className="step-num">3</span>
                  <span>Review ranked pond sites and drainage boundaries, then export GeoJSON or CSV.</span>
                </div>
              </div>
            </div>
          )}

          {/* Run summary and exports */}
          <ResultsToolbar result={analysisResult} selectedArea={selectedArea} />

          {/* Processing Notes & Caveats Banner (Renders only when caveats exist) */}
          <ProcessingNotesBanner
            status={analysisResult?.status}
            notes={analysisResult?.processing_notes}
            response={analysisResult}
          />

          {/* Recommended & Alternative Pond Sites Summary Panel */}
          <SiteSummaryPanel
            recommendedSite={analysisResult?.recommended_site}
            alternativeSites={analysisResult?.alternative_sites}
            onSelectSite={setFocusedSite}
            onPanToSite={setFocusedSite}
          />

          {/* Contributing Catchment Basin Hydrology Panel */}
          <CatchmentDetailsPanel catchment={analysisResult?.catchment} />

          {/* Precipitation Regime & Rainfall Analytics Panel */}
          <RainfallPanel
            rainfall={analysisResult?.rainfall}
            onApplyDesignRainfall={(val) => {
              setSettings((current) => ({ ...current, design_rainfall_mm: val }));
              requestAnalysis();
            }}
            defaultLat={selectedArea?.latitude || analysisResult?.recommended_site?.latitude || 21.26}
            defaultLon={selectedArea?.longitude || analysisResult?.recommended_site?.longitude || 81.28}
          />

          {/* Cluster capacity (distributed deployments only) */}
          <ClusterPanel cluster={cluster} activeProgress={isLoading ? progress : null} />

          <HistoryPanel
            entries={history}
            onRestore={handleRestore}
            onClear={() => setHistory(clearHistory())}
            disabled={isLoading}
          />
        </aside>

        {/* Right Main Area: Interactive GIS Map */}
        <main className="map-area" aria-label="Interactive GIS Map View">
          <MapView
            analysisData={analysisResult}
            focusedSite={focusedSite}
            selectedArea={selectedArea}
            selectionRadiusM={settings.radiusM}
            onAreaSelect={handleAreaSelect}
          />
        </main>
      </div>
    </div>
  );
}
