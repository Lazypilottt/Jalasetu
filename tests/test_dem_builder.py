"""
Test and CLI verification script for DEM builder service.

Usage as CLI:
    python tests/test_dem_builder.py path/to/contours.kml --output-dir ./output
    python tests/test_dem_builder.py path/to/contours.kmz --resolution 5.0

Usage via pytest:
    pytest tests/test_dem_builder.py
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to sys.path if executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService, DEMData, compute_hillshade


def run_dem_pipeline(
    file_path: str,
    output_dir: str = "./output",
    resolution: float = None,
    sample_spacing: float = None,
):
    """
    Run complete KML parsing -> DEM construction -> GeoTIFF/PNG export pipeline.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"Error: Input file '{file_path}' does not exist.")
        sys.exit(1)

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(f"Processing Contour Map: {path.name}")
    print("=" * 65)

    # 1. Parse KML / KMZ
    parser = KMLParserService()
    print("Parsing contour lines from file...")
    gdf = parser.parse(path)

    if gdf.empty:
        print("Error: No contour features extracted from the input file.")
        sys.exit(1)

    print(f"Extracted {len(gdf)} contour features with elevation data.")

    # 2. Build DEM Raster
    dem_builder = DEMBuilderService()
    print("Interpolating scattered contour points onto regular DEM grid...")
    dem_data = dem_builder.build_dem(
        gdf,
        resolution=resolution,
        sample_spacing=sample_spacing,
    )

    # 3. Report DEM properties
    min_x, min_y, max_x, max_y = dem_data.bounds
    print("\n--- DEM Generation Summary ---")
    print(f"Grid Dimensions (Rows x Cols) : {dem_data.height} x {dem_data.width} ({dem_data.height * dem_data.width:,} cells)")
    print(f"Spatial Resolution            : {dem_data.resolution:.2f} meters / cell")
    print(f"Projected CRS                 : {dem_data.crs}")
    print(f"Elevation Minimum             : {dem_data.min_elevation:.2f} m")
    print(f"Elevation Maximum             : {dem_data.max_elevation:.2f} m")
    print(f"Elevation Mean / Span         : {dem_data.mean_elevation:.2f} m (Relief: {dem_data.elevation_span:.2f} m)")
    print(f"UTM Extent (m)                : Easting [{min_x:.1f}, {max_x:.1f}], Northing [{min_y:.1f}, {max_y:.1f}]")

    # 4. Save GeoTIFF
    tif_path = out_dir / f"{path.stem}_dem.tif"
    dem_builder.save_geotiff(dem_data, tif_path)
    print(f"\n[Saved] GeoTIFF DEM Raster    : {tif_path}")

    # 5. Save Hillshade / Heatmap Visualization
    png_path = out_dir / f"{path.stem}_dem_hillshade.png"
    dem_builder.save_visualization(dem_data, png_path, contours_gdf=gdf)
    print(f"[Saved] Hillshade Visual Plot : {png_path}")

    print("=" * 65)
    print("DEM pipeline completed successfully!")
    print("=" * 65)


# =====================================================================
# Unit Tests for Pytest
# =====================================================================

def _create_synthetic_hill_contours() -> gpd.GeoDataFrame:
    """
    Create synthetic concentric circular contour lines representing a conical hill
    centered at UTM (500000, 3000000) with elevations 100m to 140m.
    """
    records = []
    center_x, center_y = 500000.0, 3000000.0

    # 5 concentric contour rings
    for elev, radius in [(100.0, 500.0), (110.0, 400.0), (120.0, 300.0), (130.0, 200.0), (140.0, 100.0)]:
        angles = np.linspace(0, 2 * np.pi, 36)
        xs = center_x + radius * np.cos(angles)
        ys = center_y + radius * np.sin(angles)
        line = LineString(np.column_stack((xs, ys)))
        records.append({"elevation": elev, "geometry": line})

    gdf = gpd.GeoDataFrame(records, columns=["elevation", "geometry"], crs="EPSG:32643")
    return gdf


def test_build_dem_synthetic_hill():
    """Verify DEM generation, shape, bounds, and no NaN values on synthetic data."""
    gdf = _create_synthetic_hill_contours()
    builder = DEMBuilderService()

    dem_data = builder.build_dem(gdf, resolution=10.0, sample_spacing=10.0)

    assert isinstance(dem_data, DEMData)
    assert dem_data.height > 0
    assert dem_data.width > 0
    assert dem_data.resolution == 10.0
    assert not np.isnan(dem_data.array).any(), "DEM array should not contain any NaN values."
    assert np.isclose(dem_data.min_elevation, 100.0, atol=2.0)
    assert np.isclose(dem_data.max_elevation, 140.0, atol=2.0)


def test_dem_geotiff_export(tmp_path):
    """Test rasterio GeoTIFF export and verify file creation."""
    gdf = _create_synthetic_hill_contours()
    builder = DEMBuilderService()
    dem_data = builder.build_dem(gdf, resolution=20.0)

    out_file = tmp_path / "test_output_dem.tif"
    saved_path = builder.save_geotiff(dem_data, out_file)

    assert saved_path.exists()
    assert saved_path.stat().st_size > 0


def test_dem_visualization_export(tmp_path):
    """Test hillshade and elevation heatmap PNG generation."""
    gdf = _create_synthetic_hill_contours()
    builder = DEMBuilderService()
    dem_data = builder.build_dem(gdf, resolution=20.0)

    out_png = tmp_path / "test_hillshade.png"
    saved_path = builder.save_visualization(dem_data, out_png, contours_gdf=gdf)

    assert saved_path.exists()
    assert saved_path.stat().st_size > 0


def test_hillshade_computation():
    """Verify numerical hillshade computation values are in [0, 255]."""
    test_grid = np.array([
        [100.0, 105.0, 110.0],
        [102.0, 108.0, 115.0],
        [104.0, 112.0, 120.0],
    ])
    hs = compute_hillshade(test_grid, resolution=10.0)
    assert hs.shape == test_grid.shape
    assert hs.dtype == np.uint8
    assert np.all(hs >= 0) and np.all(hs <= 255)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and visualize DEM from KML/KMZ contour map.")
    parser.add_argument("file_path", nargs="?", help="Path to input .kml or .kmz contour file")
    parser.add_argument("-o", "--output-dir", default="./output", help="Directory to save output GeoTIFF & PNG")
    parser.add_argument("-r", "--resolution", type=float, default=None, help="DEM grid cell size in meters")
    parser.add_argument("-s", "--sample-spacing", type=float, default=None, help="Sampling interval along contour lines (m)")

    args = parser.parse_args()

    if args.file_path:
        run_dem_pipeline(
            file_path=args.file_path,
            output_dir=args.output_dir,
            resolution=args.resolution,
            sample_spacing=args.sample_spacing,
        )
    else:
        print("Usage: python tests/test_dem_builder.py <path_to_kml_or_kmz> [-o ./output] [-r 5.0]")
        print("Running synthetic unit tests for DEM builder...")
        test_build_dem_synthetic_hill()
        test_hillshade_computation()
        print("All synthetic DEM builder tests passed successfully!")
