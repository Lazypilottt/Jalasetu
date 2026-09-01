import React, { useState, useRef } from 'react';
import { analyzeContourFile } from '../api/catchmentApi';

/**
 * Format file byte sizes into human-readable strings (e.g. "1.2 MB", "450 KB").
 *
 * @param {number} bytes - Size in bytes.
 * @returns {string} Formatted size string.
 */
function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/**
 * Client-side validator for contour map files.
 * Ensures the selected file is non-empty and has a .kml or .kmz extension.
 *
 * @param {File} file - The file object to validate.
 * @returns {{ valid: boolean, message: string|null }}
 */
function validateContourFile(file) {
  if (!file) {
    return { valid: false, message: 'Please select a file to upload.' };
  }
  const name = file.name || '';
  const lastDot = name.lastIndexOf('.');
  const ext = lastDot !== -1 ? name.slice(lastDot).toLowerCase() : '';

  if (ext !== '.kml' && ext !== '.kmz') {
    return {
      valid: false,
      message: `Unsupported file format "${ext || 'unknown'}". Please select a .kml or .kmz contour file.`,
    };
  }

  if (file.size === 0) {
    return {
      valid: false,
      message: 'The selected file is empty (0 bytes). Please choose a valid contour map.',
    };
  }

  return { valid: true, message: null };
}

/**
 * UploadPanel Component
 *
 * Handles contour map (.kml/.kmz) selection, drag-and-drop, client-side validation,
 * execution of the catchment analysis pipeline, and loading/error state management.
 *
 * @param {Object} props
 * @param {Function} [props.onAnalysisComplete] - Callback invoked with the CatchmentResponse upon success.
 * @param {Function} [props.onUpload] - Backwards-compatible callback alias for onAnalysisComplete.
 * @param {Function} [props.analyzeContourFn] - Optional custom analysis API function (defaults to analyzeContourFile).
 * @param {Object} [props.params] - Optional pipeline tuning parameters to pass to the API.
 */
export default function UploadPanel({
  onAnalysisComplete,
  onUpload,
  onFileSelect,
  onFileClear,
  onLoadingChange,
  onError,
  analyzeContourFn = analyzeContourFile,
  params = {},
}) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [status, setStatus] = useState('idle'); // 'idle' | 'loading' | 'error' | 'success'
  const [error, setError] = useState(null); // { status: number, message: string } | null
  const [isDragging, setIsDragging] = useState(false);

  const fileInputRef = useRef(null);
  const isLoading = status === 'loading';

  /**
   * Processes a newly selected or dropped file with client-side extension validation.
   */
  const handleFileSelection = (file) => {
    if (!file) return;

    const validation = validateContourFile(file);
    if (!validation.valid) {
      setSelectedFile(null);
      setError({ status: 400, message: validation.message });
      setStatus('error');
      if (typeof onFileClear === 'function') onFileClear();
      if (typeof onError === 'function') onError({ status: 400, message: validation.message });
    } else {
      setSelectedFile(file);
      setError(null);
      if (status === 'error') {
        setStatus('idle');
      }
      // Notify parent of new file selection to reset previous results
      if (typeof onFileSelect === 'function') {
        onFileSelect(file);
      }
    }

    // Reset file input value to allow re-selecting the same file if desired
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  /**
   * File input change handler (from Browse dialog).
   */
  const onFileInputChange = (e) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileSelection(files[0]);
    }
  };

  /**
   * Drag & Drop event handlers.
   */
  const onDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isLoading) setIsDragging(true);
  };

  const onDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isLoading) setIsDragging(true);
  };

  const onDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const onDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (isLoading) return;

    const dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length > 0) {
      handleFileSelection(dt.files[0]);
    }
  };

  /**
   * Clears the current file selection and resets state.
   */
  const handleClearFile = () => {
    if (isLoading) return;
    setSelectedFile(null);
    setError(null);
    setStatus('idle');
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    if (typeof onFileClear === 'function') {
      onFileClear();
    }
  };

  /**
   * Triggers the file browser dialog.
   */
  const handleBrowseClick = () => {
    if (isLoading) return;
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  /**
   * Dispatches the analysis API call.
   */
  const handleAnalyze = async () => {
    if (!selectedFile || isLoading) return;

    // Validate before submit
    const validation = validateContourFile(selectedFile);
    if (!validation.valid) {
      const errPayload = { status: 400, message: validation.message };
      setError(errPayload);
      setStatus('error');
      if (typeof onError === 'function') onError(errPayload);
      return;
    }

    setStatus('loading');
    setError(null);
    if (typeof onLoadingChange === 'function') onLoadingChange(true);

    try {
      const response = await analyzeContourFn(selectedFile, params);
      setStatus('success');
      setError(null);
      if (typeof onLoadingChange === 'function') onLoadingChange(false);

      // Lift result to parent
      if (typeof onAnalysisComplete === 'function') {
        onAnalysisComplete(response);
      }
      if (typeof onUpload === 'function') {
        onUpload(response);
      }
    } catch (err) {
      setStatus('error');
      const normalizedErr = {
        status: typeof err.status === 'number' ? err.status : 0,
        message: err.message || 'Something went wrong analyzing the file. Please try again.',
      };
      setError(normalizedErr);
      if (typeof onLoadingChange === 'function') onLoadingChange(false);
      if (typeof onError === 'function') onError(normalizedErr);
    }
  };

  /**
   * Returns a concise human-readable error badge title.
   */
  const getErrorBadgeText = (err) => {
    if (!err) return 'Error';
    if (err.status === 0) return 'Network Error';
    if (err.status === 400) return 'Invalid File (400)';
    if (err.status === 422) return 'Unprocessable Data (422)';
    if (err.status === 500) return 'Server Error (500)';
    return err.status ? `Error (${err.status})` : 'Error';
  };

  return (
    <div className="panel upload-panel">
      {/* Panel Header */}
      <div className="panel-header">
        <div className="panel-title-group">
          <span className="panel-icon">📁</span>
          <h3 className="panel-title">Upload Contour Map</h3>
        </div>
      </div>

      {/* Panel Body */}
      <div className="panel-body">
        {/* Hidden File Input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".kml,.kmz"
          onChange={onFileInputChange}
          style={{ display: 'none' }}
          disabled={isLoading}
          data-testid="contour-file-input"
        />

        {/* State 1: No file selected -> Interactive Dropzone */}
        {!selectedFile && (
          <div
            className={`dropzone-placeholder ${isDragging ? 'drag-over' : ''} ${isLoading ? 'is-disabled' : ''}`}
            onDragEnter={onDragEnter}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={handleBrowseClick}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                handleBrowseClick();
              }
            }}
          >
            <div className="dropzone-icon">📥</div>
            <p className="dropzone-primary-text">
              {isDragging ? 'Drop your contour file here' : 'Drag & drop your .kml or .kmz contour file here'}
            </p>
            <p className="dropzone-secondary-text">
              Supports standard elevation contour maps (.kml and .kmz files)
            </p>
            <button
              className="btn btn-primary btn-sm"
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleBrowseClick();
              }}
              disabled={isLoading}
            >
              Browse Files
            </button>
          </div>
        )}

        {/* State 2: Valid File Selected -> File Card */}
        {selectedFile && (
          <div className="selected-file-card">
            <div className="file-info-group">
              <span className="file-icon">🗺️</span>
              <div className="file-details">
                <span className="file-name" title={selectedFile.name}>
                  {selectedFile.name}
                </span>
                <span className="file-meta">
                  {formatFileSize(selectedFile.size)} • {selectedFile.name.endsWith('.kmz') ? 'KMZ Archive' : 'KML File'}
                </span>
              </div>
            </div>

            <div className="file-actions">
              <button
                className="btn btn-outline btn-sm"
                type="button"
                onClick={handleBrowseClick}
                disabled={isLoading}
                title="Select a different file"
              >
                Change
              </button>
              <button
                className="btn btn-ghost btn-sm btn-danger-ghost"
                type="button"
                onClick={handleClearFile}
                disabled={isLoading}
                title="Remove selected file"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {/* Loading State: Progress Indicator & Reassuring Non-technical Copy */}
        {isLoading && (
          <div className="loading-progress-card" role="status" aria-live="polite">
            <div className="loading-header">
              <div className="loading-spinner"></div>
              <div className="loading-text-group">
                <span className="loading-title">Analyzing terrain and identifying catchment area...</span>
                <span className="loading-subtitle">
                  Modeling elevation surface, ranking pond sweet-spots, and tracing upstream watershed.
                </span>
              </div>
            </div>
            <div className="loading-progress-bar-track">
              <div className="loading-progress-bar-fill"></div>
            </div>
          </div>
        )}

        {/* Error State: Dismissible Inline Error Banner */}
        {error && (
          <div className="error-banner" role="alert">
            <div className="error-banner-top">
              <div className="error-icon-title">
                <span className="error-icon">⚠️</span>
                <span className="error-title">Analysis Notice</span>
                <span className="error-badge">{getErrorBadgeText(error)}</span>
              </div>
              <button
                className="error-close-btn"
                type="button"
                onClick={() => setError(null)}
                title="Dismiss error message"
                aria-label="Dismiss error"
              >
                ✕
              </button>
            </div>
            <p className="error-message">{error.message}</p>

            {/* If a file is selected and error occurred, show inline retry button */}
            {selectedFile && !isLoading && (
              <div className="error-actions">
                <button
                  className="btn btn-outline btn-sm"
                  type="button"
                  onClick={handleAnalyze}
                >
                  🔄 Retry Analysis
                </button>
              </div>
            )}
          </div>
        )}

        {/* Main Action Bar */}
        {selectedFile && (
          <div className="upload-actions">
            <button
              className="btn btn-primary btn-block"
              type="button"
              onClick={handleAnalyze}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <span className="loading-spinner-sm"></span>
                  Analyzing Terrain...
                </>
              ) : error ? (
                '🔄 Retry Analysis'
              ) : (
                '🚀 Analyze Terrain & Catchment'
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
