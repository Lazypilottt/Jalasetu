import React, { useEffect, useRef, useState } from 'react';

const SECTIONS = [
  {
    id: 'start',
    title: 'Quick start',
    body: (
      <>
        <ol className="guide-steps">
          <li>
            <strong>Pick a point.</strong> Click anywhere on the map, type a village or <code>lat, lon</code> in the
            search box, or press <kbd>◎</kbd> to use your location. A circle shows the area that will be searched.
          </li>
          <li>
            <strong>Check what to avoid.</strong> In <em>Site constraints</em>, JalaSetu lists the rivers, tanks,
            buildings, schools and roads it found nearby. Untick anything you want to allow, or press
            <em> Mark on map</em> to add a well or boundary that the map does not show.
          </li>
          <li>
            <strong>Recommend a site.</strong> Press <em>Recommend a site here</em> (at the top of the side panel or in
            the map marker). Progress is shown step by step.
          </li>
          <li>
            <strong>Read the result.</strong> The <em>Results</em> tab shows the best pond site, other options, the
            area that drains into it, how much rainwater it can collect, and the local rainfall.
          </li>
        </ol>
        <p className="guide-note">
          No contour file? No problem. Where no contour map exists, JalaSetu builds the terrain from free global
          elevation data. Upload a surveyed <code>.kml</code> or <code>.kmz</code> contour map for the most
          accurate result.
        </p>
      </>
    ),
  },
  {
    id: 'features',
    title: 'What it does',
    body: (
      <ul className="guide-list">
        <li><strong>Finds natural low spots</strong> where water collects, using slope, depression depth and wetness.</li>
        <li><strong>Avoids existing infrastructure</strong> — water bodies, streams, buildings, schools, hospitals, temples, roads, railways, settlements and wells — with a safety buffer around each.</li>
        <li><strong>Traces the catchment</strong>: the land that drains into the pond, and how much runoff a design storm produces there.</li>
        <li><strong>Uses local rainfall</strong> from historical weather records to size the design storm.</li>
        <li><strong>Ranks alternatives</strong> so you can compare several candidate sites.</li>
        <li><strong>Exports</strong> results as GeoJSON (QGIS, Google Earth), CSV or JSON, and shares a link to the same point.</li>
        <li><strong>Remembers</strong> your recent analyses and settings in this browser.</li>
      </ul>
    ),
  },
  {
    id: 'map',
    title: 'Map controls',
    body: (
      <dl className="guide-defs">
        <dt>Search</dt><dd>Top left. Villages, towns, landmarks, or coordinates like <code>21.195, 81.482</code>.</dd>
        <dt>◎ Locate</dt><dd>Jump to your current position (your browser asks for permission).</dd>
        <dt>⤢ Full screen</dt><dd>Hide the side panel. Press <kbd>Esc</kbd> to return.</dd>
        <dt>☰ Layers</dt><dd>Choose the base map (Satellite, Terrain, Streets, Villages, Dark) and turn overlays on or off.</dd>
        <dt>⚡ Auto</dt><dd>When on, a recommendation starts as soon as you click a point.</dd>
        <dt>Bottom strip</dt><dd>Live coordinates under the cursor, zoom level, and what a click will do.</dd>
        <dt>Red shapes</dt><dd>No-build zones: infrastructure plus its safety buffer, and zones you marked.</dd>
        <dt>Terrain / 3D</dt><dd>After a result, switch to the terrain map or open a 3D view of the ground surface.</dd>
      </dl>
    ),
  },
  {
    id: 'settings',
    title: 'Settings explained',
    body: (
      <dl className="guide-defs">
        <dt>Preset</dt><dd><em>Quick</em> is fastest, <em>Detailed</em> uses a finer terrain grid and returns more sites.</dd>
        <dt>Selection radius</dt><dd>How far from your point to look for a pond site (50–1000 m).</dd>
        <dt>Land cover / Curve number</dt><dd>How much rain runs off instead of soaking in. Fields ≈ 75, forest ≈ 60, rocky ground ≈ 86.</dd>
        <dt>Design storm</dt><dd>Rain in one heavy day used for sizing. Left on <em>Auto</em>, the location's own value is used.</dd>
        <dt>Pond depth</dt><dd>Planned water depth; used to estimate storage.</dd>
        <dt>Safety buffer</dt><dd>Scales the clearance kept around infrastructure (×1 = default distances).</dd>
        <dt>Terrain source</dt><dd><em>Auto</em> uses contours where available and global elevation elsewhere.</dd>
        <dt>Suitability weights</dt><dd>Advanced: how much slope, depression and wetness count towards the score.</dd>
      </dl>
    ),
  },
  {
    id: 'results',
    title: 'Reading results',
    body: (
      <dl className="guide-defs">
        <dt>Suitability score</dt><dd>0–100. Above 70 is a good site; above 88 is excellent.</dd>
        <dt>Storage</dt><dd>Water the pond holds at the planned depth (m³; 1 m³ = 1,000 litres).</dd>
        <dt>Catchment</dt><dd>Area that drains into the pond (hectares).</dd>
        <dt>Expected runoff</dt><dd>Water reaching the pond in one design storm. If it is much smaller than storage, the pond may not fill.</dd>
        <dt>Avoided</dt><dd>Which infrastructure was kept out, and how much land was excluded.</dd>
        <dt>Processing notes</dt><dd>Warnings about data quality — read them before relying on a result.</dd>
      </dl>
    ),
  },
  {
    id: 'data',
    title: 'Data sources',
    body: (
      <>
        <p className="guide-note">Every service JalaSetu uses is free, needs no API key, and is built on open data.</p>
        <table className="guide-table">
          <thead>
            <tr><th>Used for</th><th>Source</th><th>Licence</th></tr>
          </thead>
          <tbody>
            <tr><td>Satellite map</td><td>Sentinel-2 cloudless 2024 (EOX)</td><td>CC BY-NC-SA 4.0</td></tr>
            <tr><td>Streets, villages, dark map</td><td>OpenStreetMap, Humanitarian OSM Team</td><td>ODbL</td></tr>
            <tr><td>Terrain map</td><td>OpenTopoMap</td><td>CC-BY-SA</td></tr>
            <tr><td>Place search</td><td>Nominatim (OpenStreetMap)</td><td>ODbL</td></tr>
            <tr><td>Existing infrastructure</td><td>Overpass API (OpenStreetMap)</td><td>ODbL</td></tr>
            <tr><td>Rainfall</td><td>Open-Meteo, ERA5 reanalysis</td><td>CC BY 4.0</td></tr>
            <tr><td>Elevation where no contours exist</td><td>Terrain Tiles (AWS Open Data, SRTM-derived)</td><td>Public domain / open</td></tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    id: 'tips',
    title: 'Tips & limits',
    body: (
      <ul className="guide-list">
        <li>The infrastructure check can take up to a minute when OpenStreetMap is busy. It starts as soon as you pick a point, so pick first and adjust settings while it runs.</li>
        <li>OpenStreetMap is incomplete in many villages. Mark wells, houses and field boundaries yourself if they are missing.</li>
        <li>Global elevation is about 30 m detail: good for screening, not for design. Use surveyed contours before construction.</li>
        <li>Results are a planning aid. A field visit, soil test and land-ownership check are always needed.</li>
        <li>Use the theme button (◐) in the header to switch between system, light and dark.</li>
      </ul>
    ),
  },
];

/**
 * In-app guide: quick start, features, controls, settings, results and data
 * sources. Opens from the header and once automatically on a first visit.
 */
export default function HelpGuide({ isOpen, onClose, initialSection = 'start' }) {
  const [active, setActive] = useState(initialSection);
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  // Parents re-render often (cluster polling); keep the latest handler without
  // re-running the open effect, which would reset the section and focus.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return undefined;
    setActive(initialSection);
    const previous = document.activeElement;
    closeRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') onCloseRef.current();
      if (event.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll('button, a[href], input, [tabindex]:not([tabindex="-1"])');
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, [isOpen, initialSection]);

  if (!isOpen) return null;
  const index = SECTIONS.findIndex((s) => s.id === active);
  const section = SECTIONS[index] || SECTIONS[0];

  return (
    <div className="guide-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title" ref={dialogRef}>
        <header className="guide-header">
          <div>
            <h2 id="guide-title">How to use JalaSetu</h2>
            <p>Find a farm-pond site in three clicks.</p>
          </div>
          <button type="button" className="icon-btn guide-close" onClick={onClose} ref={closeRef} aria-label="Close guide">
            ✕
          </button>
        </header>
        <div className="guide-body">
          <nav className="guide-nav" aria-label="Guide sections">
            {SECTIONS.map((s, i) => (
              <button
                key={s.id}
                type="button"
                className={`guide-nav-item ${s.id === section.id ? 'active' : ''}`}
                onClick={() => setActive(s.id)}
                aria-current={s.id === section.id ? 'page' : undefined}
              >
                <span className="guide-nav-num">{String(i + 1).padStart(2, '0')}</span>
                {s.title}
              </button>
            ))}
          </nav>
          <section className="guide-content" aria-live="polite">
            <h3>{section.title}</h3>
            {section.body}
          </section>
        </div>
        <footer className="guide-footer">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setActive(SECTIONS[Math.max(0, index - 1)].id)} disabled={index <= 0}>
            ← Back
          </button>
          <span className="guide-progress">{index + 1} / {SECTIONS.length}</span>
          {index < SECTIONS.length - 1 ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setActive(SECTIONS[index + 1].id)}>
              Next →
            </button>
          ) : (
            <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
              Start planning
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
