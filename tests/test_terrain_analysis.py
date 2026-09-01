"""
Test and CLI verification script for the full terrain analysis pipeline:
KML Parser -> DEM Builder -> Terrain Analysis

Usage as CLI:
    python tests/test_terrain_analysis.py path/to/contours.kml --output-dir ./output
    python tests/test_terrain_analysis.py path/to/contours.kmz --max-slope 8.0 --resolution 5.0

Usage via pytest:
    pytest tests/test_terrain_analysis.py
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path if executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from affine import Affine
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService, DEMData
from app.services.terrain_analysis import (
    TerrainAnalysisService,
    TerrainAnalysisResult,
    analyze_terrain,
)


def run_terrain_pipeline(
    file_path: str,
    output_dir: str = "./output",
    resolution: float = None,
    ideal_slope_deg: float = 3.0,
    max_slope_deg: float = 8.0,
    neighborhood_radius_m: float = None,
    weight_slope: float = 0.5,
    weight_depression: float = 0.5,
    suitability_threshold: float = 60.0,
):
    """
    Execute full pipeline: KML parse -> DEM build -> Terrain analysis -> GeoTIFF/PNG export.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"Error: Input file '{file_path}' does not exist.")
        sys.exit(1)

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(f"Executing Terrain Analysis Pipeline: {path.name}")
    print("=" * 70)

    # 1. Parse KML/KMZ
    print("\n[Step 1/3] Parsing contour map with KMLParserService...")
    parser = KMLParserService()
    gdf = parser.parse(path)
    if gdf.empty:
        print("Error: No contour features extracted from the input file.")
        sys.exit(1)
    print(f"  --> Extracted {len(gdf)} contour features (Elevations: {gdf['elevation'].min():.1f}m to {gdf['elevation'].max():.1f}m)")

    # 2. Build DEM
    print("\n[Step 2/3] Generating regular DEM with DEMBuilderService...")
    dem_builder = DEMBuilderService()
    dem_data = dem_builder.build_dem(gdf, resolution=resolution)
    print(f"  --> DEM shape: {dem_data.height} x {dem_data.width} ({dem_data.resolution:.1f}m resolution, CRS: {dem_data.crs})")
    print(f"  --> Elevation range: {dem_data.min_elevation:.2f}m to {dem_data.max_elevation:.2f}m")

    # 3. Terrain Analysis
    print("\n[Step 3/3] Running TerrainAnalysisService...")
    terrain_service = TerrainAnalysisService()
    analysis = terrain_service.analyze_terrain(
        dem_data=dem_data,
        ideal_slope_deg=ideal_slope_deg,
        max_slope_deg=max_slope_deg,
        neighborhood_radius_m=neighborhood_radius_m,
        weight_slope=weight_slope,
        weight_depression=weight_depression,
        suitability_threshold=suitability_threshold,
    )

    # Summary Statistics
    slope_deg = analysis.slope_degrees
    suit_score = analysis.suitability_score

    pct_gentle = float(np.count_nonzero(slope_deg <= ideal_slope_deg) / slope_deg.size * 100.0)
    pct_allowable = float(np.count_nonzero(slope_deg <= max_slope_deg) / slope_deg.size * 100.0)

    print("\n" + "-" * 40)
    print("--- Terrain Analysis Results ---")
    print("-" * 40)
    print(f"Slope (Degrees)       : Min = {np.min(slope_deg):.2f}°, Max = {np.max(slope_deg):.2f}°, Mean = {np.mean(slope_deg):.2f}°")
    print(f"Gentle Slopes (≤{ideal_slope_deg}°) : {pct_gentle:.1f}% of total area")
    print(f"Excavatable (≤{max_slope_deg}°)  : {pct_allowable:.1f}% of total area")
    print(f"Suitability Score     : Min = {np.min(suit_score):.1f}, Max = {np.max(suit_score):.1f}, Mean = {np.mean(suit_score):.1f} / 100")
    print(f"Pond Sweet-Spots (≥{suitability_threshold}) : {analysis.suitable_area_percentage:.1f}% of total area classified as highly suitable")

    # Export GeoTIFFs
    slope_tif_path = out_dir / f"{path.stem}_slope.tif"
    terrain_service.save_geotiff(analysis.slope_degrees, dem_data, slope_tif_path)

    suit_tif_path = out_dir / f"{path.stem}_suitability.tif"
    terrain_service.save_geotiff(analysis.suitability_score, dem_data, suit_tif_path)

    # Export Visualization
    viz_path = out_dir / f"{path.stem}_terrain_analysis.png"
    terrain_service.save_analysis_visualization(analysis, viz_path)

    print("\n" + "-" * 40)
    print("--- Generated Output Files ---")
    print("-" * 40)
    print(f"[Saved] Slope Raster GeoTIFF       : {slope_tif_path}")
    print(f"[Saved] Suitability Raster GeoTIFF : {suit_tif_path}")
    print(f"[Saved] Multi-panel Visual Summary : {viz_path}")
    print("=" * 70)
    print("Pipeline finished successfully!")
    print("=" * 70)


# =====================================================================
# Unit Tests for Pytest
# =====================================================================

def _create_planar_ramp_dem(slope_rise_run: float = 0.1, resolution: float = 10.0) -> DEMData:
    """
    Creates a planar DEM sloping purely in the X direction with slope = slope_rise_run.
    Expected slope angle = arctan(slope_rise_run) in degrees.
    """
    rows, cols = 50, 50
    x_indices = np.arange(cols)
    # Elevation increases by (slope_rise_run * resolution) per column
    elev_row = 100.0 + x_indices * (slope_rise_run * resolution)
    elev_array = np.tile(elev_row, (rows, 1))

    transform = Affine(resolution, 0.0, 500000.0, 0.0, -resolution, 3000000.0)
    return DEMData(
        array=elev_array,
        transform=transform,
        crs="EPSG:32643",
        nodata=-9999.0,
        resolution=resolution,
        bounds=(500000.0, 3000000.0 - rows * resolution, 500000.0 + cols * resolution, 3000000.0),
    )


def _create_synthetic_bowl_dem(resolution: float = 10.0) -> DEMData:
    """
    Creates a synthetic valley/bowl DEM where the center is the lowest elevation (local depression).
    """
    rows, cols = 60, 60
    y, x = np.ogrid[:rows, :cols]
    cx, cy = cols // 2, rows // 2
    dist_sq = (x - cx) ** 2 + (y - cy) ** 2
    # Bowl shape: center is 100m, rises radially to 150m at edges
    elev_array = 100.0 + (dist_sq / float(cx**2 + cy**2)) * 50.0

    transform = Affine(resolution, 0.0, 500000.0, 0.0, -resolution, 3000000.0)
    return DEMData(
        array=elev_array,
        transform=transform,
        crs="EPSG:32643",
        nodata=-9999.0,
        resolution=resolution,
        bounds=(500000.0, 3000000.0 - rows * resolution, 500000.0 + cols * resolution, 3000000.0),
    )


def test_slope_computation_planar_ramp():
    """Verify finite-difference slope matches theoretical analytical angle on a planar slope."""
    rise_run = 0.08  # 8% slope -> arctan(0.08) ~ 4.5739 degrees
    expected_deg = np.degrees(np.arctan(rise_run))

    dem_data = _create_planar_ramp_dem(slope_rise_run=rise_run, resolution=10.0)
    service = TerrainAnalysisService()
    slope_deg, slope_pct = service.compute_slope(dem_data)

    # Interior cells should match expected angle with high precision
    interior_slope = slope_deg[5:-5, 5:-5]
    assert np.allclose(interior_slope, expected_deg, atol=0.01)
    assert np.allclose(slope_pct[5:-5, 5:-5], rise_run * 100.0, atol=0.01)


def test_depression_and_suitability_bowl():
    """Verify that a hollow/bowl center receives top depression and suitability scores."""
    dem_data = _create_synthetic_bowl_dem(resolution=10.0)
    service = TerrainAnalysisService()
    analysis = service.analyze_terrain(
        dem_data=dem_data,
        ideal_slope_deg=4.0,
        max_slope_deg=10.0,
        weight_slope=0.5,
        weight_depression=0.5,
    )

    cx, cy = dem_data.width // 2, dem_data.height // 2

    # Center of bowl is flat and the lowest point in its neighborhood
    center_slope = analysis.slope_degrees[cy, cx]
    center_depression = analysis.depression_index[cy, cx]
    center_suitability = analysis.suitability_score[cy, cx]

    assert center_slope < 1.0, "Center of circular bowl should be virtually flat"
    assert center_depression > 90.0, "Center of circular bowl should have high depression score"
    assert center_suitability > 90.0, "Center of circular bowl should have very high suitability score"
    assert analysis.suitable_mask[cy, cx] == True, "Center of circular bowl must be in suitable mask"


def test_terrain_analysis_export_geotiff_and_viz(tmp_path):
    """Test GeoTIFF and visualization PNG saving."""
    dem_data = _create_synthetic_bowl_dem(resolution=10.0)
    service = TerrainAnalysisService()
    analysis = service.analyze_terrain(dem_data)

    out_tif = tmp_path / "test_suitability.tif"
    saved_tif = service.save_geotiff(analysis.suitability_score, dem_data, out_tif)
    assert saved_tif.exists()
    assert saved_tif.stat().st_size > 0

    out_png = tmp_path / "test_terrain_viz.png"
    saved_png = service.save_analysis_visualization(analysis, out_png)
    assert saved_png.exists()
    assert saved_png.stat().st_size > 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run complete KML -> DEM -> Terrain Analysis pipeline.")
    parser.add_argument("file_path", nargs="?", help="Path to input .kml or .kmz contour file")
    parser.add_argument("-o", "--output-dir", default="./output", help="Directory to save output GeoTIFFs & PNG")
    parser.add_argument("-r", "--resolution", type=float, default=None, help="DEM grid cell size in meters")
    parser.add_argument("--ideal-slope", type=float, default=3.0, help="Ideal slope threshold in degrees (default: 3.0)")
    parser.add_argument("--max-slope", type=float, default=8.0, help="Maximum permissible slope threshold in degrees (default: 8.0)")
    parser.add_argument("--window-radius", type=float, default=None, help="Neighborhood filter radius in meters for depression detection")
    parser.add_argument("--weight-slope", type=float, default=0.5, help="Weight for slope criterion (default: 0.5)")
    parser.add_argument("--weight-depression", type=float, default=0.5, help="Weight for depression criterion (default: 0.5)")
    parser.add_argument("--threshold", type=float, default=60.0, help="Suitability score threshold [0-100] (default: 60.0)")

    args = parser.parse_args()

    if args.file_path:
        run_terrain_pipeline(
            file_path=args.file_path,
            output_dir=args.output_dir,
            resolution=args.resolution,
            ideal_slope_deg=args.ideal_slope,
            max_slope_deg=args.max_slope,
            neighborhood_radius_m=args.window_radius,
            weight_slope=args.weight_slope,
            weight_depression=args.weight_depression,
            suitability_threshold=args.threshold,
        )
    else:
        print("Usage: python tests/test_terrain_analysis.py <path_to_kml_or_kmz> [-o ./output]")
        print("Running unit tests on synthetic terrain models...")
        test_slope_computation_planar_ramp()
        test_depression_and_suitability_bowl()
        print("All synthetic terrain analysis tests passed successfully!")
