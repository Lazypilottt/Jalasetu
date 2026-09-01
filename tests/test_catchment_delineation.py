"""
Test and CLI verification script for Full Catchment Delineation Pipeline:
KML Parser -> DEM Builder -> Terrain Analysis -> Pond Siting -> Catchment Delineation

Usage as CLI:
    python tests/test_catchment_delineation.py path/to/contours.kml --output-dir ./output
    python tests/test_catchment_delineation.py path/to/contours.kmz --candidate-rank 1 --snap-radius 30.0

Usage via pytest:
    pytest tests/test_catchment_delineation.py
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any

# Add project root to sys.path if executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from affine import Affine
import numpy as np
import pytest

from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService, DEMData
from app.services.terrain_analysis import TerrainAnalysisService
from app.services.pond_site import PondSiteService
from app.services.catchment_delineation import (
    CatchmentDelineationService,
    CatchmentResult,
    delineate_catchment,
)


def run_full_catchment_pipeline(
    file_path: str,
    output_dir: str = "./output",
    resolution: float = None,
    candidate_rank: int = 1,
    snap_radius_meters: float = 25.0,
):
    """
    Execute full pipeline: KML -> DEM -> Terrain -> Pond Site -> Watershed Delineation -> Export.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"Error: Input file '{file_path}' does not exist.")
        sys.exit(1)

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print(f"Executing End-to-End Catchment Pipeline: {path.name}")
    print("=" * 75)

    # 1. Parse KML/KMZ
    print("\n[1/5] Parsing contour map (KMLParserService)...")
    parser = KMLParserService()
    gdf = parser.parse(path)
    if gdf.empty:
        print("Error: No contour features extracted from the input file.")
        sys.exit(1)
    print(f"  --> Extracted {len(gdf)} contour features.")

    # 2. Build DEM
    print("\n[2/5] Generating regular DEM (DEMBuilderService)...")
    dem_builder = DEMBuilderService()
    dem_data = dem_builder.build_dem(gdf, resolution=resolution)
    print(f"  --> DEM shape: {dem_data.height} x {dem_data.width} ({dem_data.resolution:.1f}m cell size, {dem_data.crs})")

    # 3. Terrain Analysis
    print("\n[3/5] Computing slope and suitability rasters (TerrainAnalysisService)...")
    terrain_service = TerrainAnalysisService()
    analysis = terrain_service.analyze_terrain(dem_data)

    # 4. Extract Candidate Pond Sites
    print("\n[4/5] Identifying candidate pond locations (PondSiteService)...")
    pond_service = PondSiteService()
    siting_result = pond_service.identify_candidate_sites(analysis, top_n=5)

    if not siting_result.candidates:
        print("Error: No candidate pond sites found. Cannot delineate catchment.")
        sys.exit(1)

    # Select target candidate
    selected_idx = min(max(1, candidate_rank), len(siting_result.candidates)) - 1
    target_site = siting_result.candidates[selected_idx]

    print(f"  --> Selected Target: Rank #{target_site.rank} ({target_site.site_id})")
    print(f"      Location : {target_site.latitude:.6f}°N, {target_site.longitude:.6f}°E")
    print(f"      UTM Coord: {target_site.utm_x:.1f}m E, {target_site.utm_y:.1f}m N")
    print(f"      Pond Area: {target_site.area_m2:.0f} m² (Suitability: {target_site.mean_suitability:.1f}/100)")

    # 5. Catchment Delineation
    print("\n[5/5] Delineating upstream contributing catchment (CatchmentDelineationService)...")
    catchment_service = CatchmentDelineationService()
    result = catchment_service.delineate(
        dem_data=dem_data,
        pour_point=target_site,
        snap_radius_meters=snap_radius_meters,
    )

    print("\n" + "-" * 45)
    print("--- Delineated Catchment Summary ---")
    print("-" * 45)
    print(f"Delineation Engine       : {result.method_used}")
    print(f"Snapped Stream Outlet    : {result.snapped_pour_point_wgs84[0]:.6f}°N, {result.snapped_pour_point_wgs84[1]:.6f}°E")
    print(f"Catchment Area           : {result.area_m2:,.1f} m² ({result.area_ha:.3f} hectares / {result.area_ha/100:.4f} km²)")
    print(f"Total Drainage Grid Cells: {result.cell_count:,} cells")
    print(f"Catchment Elevation Range: {result.min_elevation:.2f}m to {result.max_elevation:.2f}m (Relief: {result.elevation_span:.2f}m)")
    print(f"Mean Basin Elevation     : {result.mean_elevation:.2f} m")
    print(f"Mean Basin Slope         : {result.mean_slope_deg:.2f}° ({result.mean_slope_pct:.1f}%)")

    # Export GeoJSON
    geojson_path = out_dir / f"{path.stem}_{target_site.site_id}_catchment.geojson"
    catchment_service.save_geojson(result, geojson_path)

    # Export Visualization
    viz_path = out_dir / f"{path.stem}_{target_site.site_id}_catchment_overlay.png"
    catchment_service.save_catchment_visualization(result, viz_path, candidate_site=target_site)

    print("\n" + "-" * 45)
    print("--- Exported Artifacts ---")
    print("-" * 45)
    print(f"[Saved] Catchment GeoJSON Boundary : {geojson_path}")
    print(f"[Saved] Catchment Visual Overlay   : {viz_path}")
    print("=" * 75)
    print("Full catchment pipeline completed successfully!")
    print("=" * 75)


# =====================================================================
# Unit Tests for Pytest
# =====================================================================

def _create_synthetic_v_valley_dem(resolution: float = 10.0) -> Tuple[DEMData, Tuple[int, int]]:
    """
    Creates a synthetic V-shaped valley DEM draining toward the south-central outlet.
    Elevation increases with distance from center column and from bottom row.
    Outlet is at (rows-1, cols//2).
    """
    rows, cols = 50, 50
    cy = cols // 2
    r_idx, c_idx = np.ogrid[:rows, :cols]

    # V-groove channel along column cy
    dist_from_channel = np.abs(c_idx - cy)
    # Downslope gradient toward row (rows-1)
    downslope = (rows - 1 - r_idx) * 0.8

    elev = 100.0 + downslope + dist_from_channel * 1.2

    origin_x, origin_y = 500000.0, 3000000.0
    transform = Affine(resolution, 0.0, origin_x, 0.0, -resolution, origin_y)

    dem_data = DEMData(
        array=elev,
        transform=transform,
        crs="EPSG:32643",
        nodata=-9999.0,
        resolution=resolution,
        bounds=(origin_x, origin_y - rows * resolution, origin_x + cols * resolution, origin_y),
    )
    return dem_data, (rows - 2, cy)


def test_catchment_delineation_synthetic_v_valley():
    """Verify that a pour point at the outlet of a V-valley captures the upstream basin."""
    dem_data, (outlet_r, outlet_c) = _create_synthetic_v_valley_dem(resolution=10.0)
    service = CatchmentDelineationService()

    # Target UTM coordinates at valley outlet
    utm_x = dem_data.transform.c + dem_data.transform.a * (outlet_c + 0.5)
    utm_y = dem_data.transform.f + dem_data.transform.e * (outlet_r + 0.5)

    result = service.delineate(
        dem_data=dem_data,
        pour_point=(utm_x, utm_y),
        snap_radius_meters=15.0,
    )

    assert isinstance(result, CatchmentResult)
    assert result.cell_count > 100, "V-valley basin should capture significant upstream cells"
    assert result.area_m2 > 10000.0
    assert result.area_ha > 1.0
    assert result.elevation_span > 10.0
    assert result.polygon_utm.is_valid
    assert not result.polygon_utm.is_empty


def test_catchment_geojson_export(tmp_path):
    """Verify GeoJSON export structure and metadata properties."""
    dem_data, (outlet_r, outlet_c) = _create_synthetic_v_valley_dem(resolution=10.0)
    service = CatchmentDelineationService()

    utm_x = dem_data.transform.c + dem_data.transform.a * (outlet_c + 0.5)
    utm_y = dem_data.transform.f + dem_data.transform.e * (outlet_r + 0.5)

    result = service.delineate(dem_data=dem_data, pour_point=(utm_x, utm_y))

    out_json = tmp_path / "test_catchment.geojson"
    saved_path = service.save_geojson(result, out_json)

    assert saved_path.exists()
    with open(saved_path, "r") as f:
        data = json.load(f)

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert "area_m2" in props
    assert "elevation_meters" in props
    assert "mean_slope_degrees" in props


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delineate upstream catchment for candidate pond sites.")
    parser.add_argument("file_path", nargs="?", help="Path to input .kml or .kmz contour file")
    parser.add_argument("-o", "--output-dir", default="./output", help="Output directory")
    parser.add_argument("-r", "--resolution", type=float, default=None, help="DEM grid cell size in meters")
    parser.add_argument("--candidate-rank", type=int, default=1, help="Rank of candidate pond site to delineate (default: 1)")
    parser.add_argument("--snap-radius", type=float, default=25.0, help="Search radius in meters to snap pour point to stream channel")

    args = parser.parse_args()

    if args.file_path:
        run_full_catchment_pipeline(
            file_path=args.file_path,
            output_dir=args.output_dir,
            resolution=args.resolution,
            candidate_rank=args.candidate_rank,
            snap_radius_meters=args.snap_radius,
        )
    else:
        print("Usage: python tests/test_catchment_delineation.py <path_to_kml_or_kmz> [-o ./output] [--candidate-rank 1]")
        print("Running unit tests on synthetic V-valley terrain...")
        test_catchment_delineation_synthetic_v_valley()
        print("All synthetic catchment delineation tests passed successfully!")
