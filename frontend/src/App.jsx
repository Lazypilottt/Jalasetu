import React, { useState } from 'react';
import UploadPanel from './components/UploadPanel';
import MapView from './components/MapView';
import SiteSummaryPanel from './components/SiteSummaryPanel';
import CatchmentDetailsPanel from './components/CatchmentDetailsPanel';
import ProcessingNotesBanner from './components/ProcessingNotesBanner';

/**
 * Main Jalasetu Application Component
 *
 * Coordinates end-to-end user workflows:
 *  - File upload, client-side validation, and FastAPI backend pipeline execution
 *  - Global state management (uploaded file, CatchmentResponse, loading/error states, focused site)
 *  - Automatic map view synchronization and result layer rendering
 *  - Allows re-uploading a new file at any time to clear previous results and reset the map
 */
export default function App() {
  const [uploadedFile, setUploadedFile] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [focusedSite, setFocusedSite] = useState(null);

  /**
   * Invoked when a new file is chosen or dropped in the UploadPanel.
   * Clears any previous analysis results and resets the map view.
   */
  const handleFileSelect = (file) => {
    setUploadedFile(file);
    setAnalysisResult(null);
    setAnalysisError(null);
    setFocusedSite(null);
  };

  /**
   * Invoked when the user clears the selected file.
   */
  const handleFileClear = () => {
    setUploadedFile(null);
    setAnalysisResult(null);
    setAnalysisError(null);
    setFocusedSite(null);
    setIsLoading(false);
  };

  /**
   * Invoked upon successful API analysis response.
   *
   * @param {Object} response - CatchmentResponse payload.
   */
  const handleAnalysisComplete = (response) => {
    setAnalysisResult(response);
    setAnalysisError(null);
    setFocusedSite(null);
    setIsLoading(false);
  };

  /**
   * Invoked upon API analysis failure.
   */
  const handleAnalysisError = (err) => {
    setAnalysisError(err);
    setIsLoading(false);
  };

  // Derive human-readable header status indicator
  const getHeaderStatus = () => {
    if (isLoading) {
      return {
        dotClass: 'status-dot status-dot-loading',
        label: 'Analyzing Terrain...',
        badgeClass: 'badge-header-loading',
      };
    }
    if (analysisResult) {
      return {
        dotClass: 'status-dot status-dot-success',
        label: 'Analysis Complete',
        badgeClass: 'badge-header-success',
      };
    }
    if (analysisError) {
      return {
        dotClass: 'status-dot status-dot-error',
        label: 'Analysis Failed',
        badgeClass: 'badge-header-error',
      };
    }
    if (uploadedFile) {
      return {
        dotClass: 'status-dot status-dot-ready',
        label: 'Ready to Analyze',
        badgeClass: 'badge-header-ready',
      };
    }
    return {
      dotClass: 'status-dot',
      label: 'Waiting for Contour Upload',
      badgeClass: '',
    };
  };

  const headerStatus = getHeaderStatus();

  return (
    <div className="app-container">
      {/* Top Application Header */}
      <header className="app-header">
        <div className="brand-section">
          <span className="brand-logo-icon" role="img" aria-label="Jalasetu Water Drop">
            💧
          </span>
          <div>
            <h1 className="brand-title">JalaSetu</h1>
            <p className="brand-tagline">Smarter farm pond siting & catchment analysis for villages</p>
          </div>
        </div>

        {/* Dynamic Global Status Badge */}
        <div className={`header-status-badge ${headerStatus.badgeClass}`}>
          <span className={headerStatus.dotClass}></span>
          <span>{headerStatus.label}</span>
        </div>
      </header>

      {/* Main Split Layout: Sidebar Controls + Interactive GIS Map */}
      <div className="main-layout">
        {/* Left Sidebar Area for Controls and Result Panels */}
        <aside className="sidebar-area" aria-label="Control and Analysis Panels">
          {/* 1. Contour Map Upload Panel */}
          <UploadPanel
            onAnalysisComplete={handleAnalysisComplete}
            onUpload={handleAnalysisComplete}
            onFileSelect={handleFileSelect}
            onFileClear={handleFileClear}
            onLoadingChange={setIsLoading}
            onError={handleAnalysisError}
          />

          {/* 2. Welcome Intro Card (Shown on First Load / Landing State) */}
          {!analysisResult && !uploadedFile && (
            <div className="welcome-intro-card" role="region" aria-label="About Jalasetu">
              <div className="welcome-header">
                <span className="welcome-icon">🌱</span>
                <h3 className="welcome-title">Village Pond Siting Assistant</h3>
              </div>
              <p className="welcome-text">
                Jalasetu analyzes topographic contour maps to identify natural low-lying depressions and calculate upstream rainwater catchment areas for optimal farm pond placement.
              </p>
              <div className="welcome-steps">
                <div className="welcome-step-item">
                  <span className="step-num">1</span>
                  <span>Upload a contour map (.kml or .kmz) to begin.</span>
                </div>
                <div className="welcome-step-item">
                  <span className="step-num">2</span>
                  <span>Review ranked pond excavation sweet-spots and drainage boundaries on the interactive map.</span>
                </div>
              </div>
            </div>
          )}

          {/* 3. Processing Notes & Caveats Banner (Renders only when caveats exist) */}
          <ProcessingNotesBanner
            status={analysisResult?.status}
            notes={analysisResult?.processing_notes}
            response={analysisResult}
          />

          {/* 4. Recommended & Alternative Pond Sites Summary Panel */}
          <SiteSummaryPanel
            recommendedSite={analysisResult?.recommended_site}
            alternativeSites={analysisResult?.alternative_sites}
            onSelectSite={setFocusedSite}
            onPanToSite={setFocusedSite}
          />

          {/* 5. Contributing Catchment Basin Hydrology Panel */}
          <CatchmentDetailsPanel catchment={analysisResult?.catchment} />
        </aside>

        {/* Right Main Area: Interactive GIS Map */}
        <main className="map-area" aria-label="Interactive GIS Map View">
          <MapView
            analysisData={analysisResult}
            focusedSite={focusedSite}
          />
        </main>
      </div>
    </div>
  );
}
