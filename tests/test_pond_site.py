"""
Test and CLI verification script for Pond Site Identification Service:
KML Parser -> DEM Builder -> Terrain Analysis -> Pond Site Selection

Usage as CLI:
    python tests/test_pond_site.py path/to/contours.kml --output-dir ./output
    python tests/test_pond_site.py path/to/contours.kmz --min-suitability 60.0 --min-area 250.0

Usage via pytest:
    pytest tests/test_pond_site.py
"""

import argparse
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
from shapely.geometry import Point, shape

from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService, DEMData
from app.services.terrain_analysis import TerrainAnalysisService, TerrainAnalysisResult
from app.services.pond_site import PondSiteService, PondSiteCandidate, find_candidate_pond_sites


def run_pond_siting_pipeline(
    file_path: str,
    output_dir: str = "./output",
    resolution: float = None,
    min_suitability_threshold: float = 60.0,
    min_area_m2: float = 200.0,
    top_n: int = 5,
):
    """
    Execute full pipeline from KML parse through candidate pond site selection.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"Error: Input file '{file_path}' does not exist.")
        sys.exit(1)

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print(f"Executing End-to-End Pond Siting Pipeline: {path.name}")
    print("=" * 75)

    # 1. Parse KML
    print("\n[1/4] Parsing contour map (KMLParserService)...")
    parser = KMLParserService()
    gdf = parser.parse(path)
    if gdf.empty:
        print("Error: No contour features extracted from the input file.")
        sys.exit(1)
    print(f"  --> Extracted {len(gdf)} contour features.")

    # 2. Build DEM
    print("\n[2/4] Interpolating DEM surface (DEMBuilderService)...")
    dem_builder = DEMBuilderService()
    dem_data = dem_builder.build_dem(gdf, resolution=resolution)
    print(f"  --> DEM Shape: {dem_data.height} x {dem_data.width} ({dem_data.resolution:.1f}m cell size, {dem_data.crs})")

    # 3. Terrain Analysis
    print("\n[3/4] Computing slope and suitability rasters (TerrainAnalysisService)...")
    terrain_service = TerrainAnalysisService()
    analysis = terrain_service.analyze_terrain(dem_data)
    print(f"  --> Mean terrain slope: {analysis.mean_slope_deg:.2f}°")
    print(f"  --> Suitable area: {analysis.suitable_area_percentage:.1f}%")

    # 4. Pond Site Extraction & Ranking
    print("\n[4/4] Extracting and ranking candidate pond locations (PondSiteService)...")
    pond_service = PondSiteService()
    siting_result = pond_service.identify_candidate_sites(
        analysis_result=analysis,
        min_suitability_threshold=min_suitability_threshold,
        min_area_m2=min_area_m2,
        top_n=top_n,
    )

    candidates = siting_result.candidates
    print(f"\nIdentified {len(candidates)} qualified candidate pond sites (min area: {min_area_m2:.0f}m², min suitability: {min_suitability_threshold:.0f}):\n")

    if not candidates:
        print("No regions met the combined area and suitability thresholds.")
        return

    # Print formatted candidate summary table
    header = f"{'Rank':<5} | {'Site ID':<8} | {'Lat, Lon (WGS84)':<24} | {'UTM East, North (m)':<24} | {'Area (m²)':<10} | {'Score':<6} | {'Elev (m)':<9} | {'Slope'}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    for c in candidates:
        lat_lon = f"{c.latitude:.6f}, {c.longitude:.6f}"
        utm_coords = f"{c.utm_x:.1f}, {c.utm_y:.1f}"
        print(
            f"#{c.rank:<4} | {c.site_id:<8} | {lat_lon:<24} | {utm_coords:<24} | "
            f"{c.area_m2:<10.0f} | {c.mean_suitability:<6.1f} | {c.mean_elevation:<9.1f} | {c.mean_slope_deg:.1f}°"
        )
    print("-" * len(header))

    # Save visual candidate sites plot
    viz_path = out_dir / f"{path.stem}_pond_candidates.png"
    pond_service.save_candidate_sites_visualization(siting_result, analysis, viz_path)
    print(f"\n[Saved] Annotated Siting Map Plot : {viz_path}")
    print("=" * 75)
    print("Pond siting pipeline completed successfully!")
    print("=" * 75)


# =====================================================================
# Unit Tests for Pytest
# =====================================================================

def _create_synthetic_bowl_analysis() -> Tuple[TerrainAnalysisResult, Tuple[int, int]]:
    """Create synthetic bowl terrain analysis with known central depression."""
    rows, cols = 80, 80
    resolution = 5.0
    cy, cx = rows // 2, cols // 2
    y, x = np.ogrid[:rows, :cols]
    dist_sq = (x - cx) ** 2 + (y - cy) ** 2

    # Elevation: center is 100m, bowl rises to 125m
    elev = 100.0 + (dist_sq / float(cx**2 + cy**2)) * 25.0

    origin_x, origin_y = 700000.0, 3000000.0
    transform = Affine(resolution, 0.0, origin_x, 0.0, -resolution, origin_y)

    dem_data = DEMData(
        array=elev,
        transform=transform,
        crs="EPSG:32643",
        nodata=-9999.0,
        resolution=resolution,
        bounds=(origin_x, origin_y - rows * resolution, origin_x + cols * resolution, origin_y),
    )

    terrain_service = TerrainAnalysisService()
    analysis = terrain_service.analyze_terrain(
        dem_data=dem_data,
        ideal_slope_deg=3.0,
        max_slope_deg=8.0,
    )
    return analysis, (cy, cx)


def test_pond_siting_identifies_central_bowl():
    """Verify that the center of the synthetic bowl is extracted as candidate #1."""
    analysis, (cy, cx) = _create_synthetic_bowl_analysis()
    service = PondSiteService()

    siting_result = service.identify_candidate_sites(
        analysis_result=analysis,
        min_suitability_threshold=60.0,
        min_area_m2=100.0,
    )

    assert siting_result.total_candidates_found >= 1
    top = siting_result.top_candidate
    assert top is not None
    assert top.rank == 1
    assert top.site_id == "site_1"

    # Centroid should be within 2 cells of bowl center (cy, cx)
    assert abs(top.raster_centroid_row - cy) <= 2.5
    assert abs(top.raster_centroid_col - cx) <= 2.5

    # Coordinates must be valid
    assert 699000 < top.utm_x < 701000
    assert 2999000 < top.utm_y < 3001000
    assert -180 <= top.longitude <= 180
    assert -90 <= top.latitude <= 90

    # Suitability & slope
    assert top.mean_suitability > 70.0
    assert top.mean_slope_deg < 3.5

    # Boundary polygon presence & validity
    assert top.polygon_utm is not None
    assert top.polygon_utm.is_valid and not top.polygon_utm.is_empty
    assert top.polygon_wgs84 is not None
    assert top.polygon_wgs84.is_valid and not top.polygon_wgs84.is_empty

    # Centroid containment within its own boundary polygon
    pt_utm = Point(top.utm_x, top.utm_y)
    assert top.polygon_utm.covers(pt_utm) or top.polygon_utm.distance(pt_utm) <= analysis.dem_data.resolution

    pt_wgs84 = Point(top.longitude, top.latitude)
    assert top.polygon_wgs84.covers(pt_wgs84) or top.polygon_wgs84.distance(pt_wgs84) <= 0.001

    # GeoJSON FeatureCollection structure
    geojson = top.to_boundary_geojson_dict()
    assert geojson is not None
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 1
    poly_geom = shape(geojson["features"][0]["geometry"])
    assert poly_geom.is_valid and not poly_geom.is_empty
    assert poly_geom.covers(pt_wgs84) or poly_geom.distance(pt_wgs84) <= 0.001


def test_pond_siting_area_filter():
    """Verify that small isolated noise components below min_area_m2 are discarded."""
    analysis, _ = _create_synthetic_bowl_analysis()
    service = PondSiteService()

    # If min_area_m2 is larger than the entire bowl suitable footprint, no candidates should pass
    siting_result = service.identify_candidate_sites(
        analysis_result=analysis,
        min_suitability_threshold=60.0,
        min_area_m2=1000000.0,  # 1 km^2 (huge)
    )
    assert len(siting_result.candidates) == 0
    assert siting_result.top_candidate is None


def test_pond_siting_rejects_linear_road_corridor():
    """
    Regression test: Verify that a flat, low-slope linear strip (road corridor)
    is rejected due to high elongation, and a compact depression is selected as the top pond site.
    """
    import scipy.ndimage as ndi

    rows, cols = 100, 100
    res = 5.0
    origin_x, origin_y = 500000.0, 3000000.0

    # Base terrain: sloping hillside
    y, x = np.ogrid[:rows, :cols]
    elev = 100.0 + (y / float(rows)) * 60.0 + np.zeros((rows, cols))

    # 1. Road corridor: perfectly flat horizontal strip along row 30 (cols 15-85)
    # 5 cells wide (25m), 70 cells long (350m) -> area = 8750 m² with 0 slope
    elev[28:33, 15:85] = 118.0

    # 2. Compact natural depression: flat circular bowl at (70, 50) with radius 8 cells (40m)
    # area ~ 5000 m²
    dist_sq = (x - 50) ** 2 + (y - 70) ** 2
    elev[dist_sq <= 64] = 110.0

    # Apply slight gaussian smoothing to simulate continuous DEM interpolation
    elev = ndi.gaussian_filter(elev, sigma=1.0)

    dem_data = DEMData(
        array=elev,
        transform=Affine(res, 0.0, origin_x, 0.0, -res, origin_y),
        crs="EPSG:32643",
        nodata=-9999.0,
        resolution=res,
        bounds=(origin_x, origin_y - rows * res, origin_x + cols * res, origin_y),
    )

    terrain_service = TerrainAnalysisService()
    analysis = terrain_service.analyze_terrain(
        dem_data=dem_data,
        ideal_slope_deg=3.0,
        max_slope_deg=6.0,
        suitability_threshold=50.0,
    )

    service = PondSiteService()

    # Siting with shape filtering enabled (default max_elongation_ratio=3.5)
    siting_result = service.identify_candidate_sites(
        analysis_result=analysis,
        min_suitability_threshold=50.0,
        min_area_m2=200.0,
        max_elongation_ratio=3.5,
    )

    # 1. Assert linear road candidate was rejected
    assert siting_result.rejected_elongated_count >= 1
    assert any("road/corridor" in note.lower() or "elongation" in note.lower() for note in siting_result.notes)

    # 2. Assert top candidate is the compact bowl at (70, 50)
    top = siting_result.top_candidate
    assert top is not None
    assert top.rank == 1
    assert abs(top.raster_centroid_row - 70.0) <= 4.0
    assert abs(top.raster_centroid_col - 50.0) <= 4.0

    # 3. Assert top candidate has compact shape (low elongation ratio)
    assert top.elongation_ratio <= 3.5
    assert top.area_m2 >= 1000.0

    # 4. Assert none of the selected candidate sites are on the road corridor (row ~ 30)
    for cand in siting_result.candidates:
        assert not (25.0 <= cand.raster_centroid_row <= 35.0), f"Site {cand.site_id} landed on the road corridor!"
        assert cand.elongation_ratio <= 3.5


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract and rank candidate pond locations.")
    parser.add_argument("file_path", nargs="?", help="Path to input .kml or .kmz contour file")
    parser.add_argument("-o", "--output-dir", default="./output", help="Output directory")
    parser.add_argument("-r", "--resolution", type=float, default=None, help="DEM grid cell size in meters")
    parser.add_argument("--min-suitability", type=float, default=60.0, help="Minimum suitability threshold [0-100]")
    parser.add_argument("--min-area", type=float, default=200.0, help="Minimum pond footprint area in m²")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top candidates to report")

    args = parser.parse_args()

    if args.file_path:
        run_pond_siting_pipeline(
            file_path=args.file_path,
            output_dir=args.output_dir,
            resolution=args.resolution,
            min_suitability_threshold=args.min_suitability,
            min_area_m2=args.min_area,
            top_n=args.top_n,
        )
    else:
        print("Usage: python tests/test_pond_site.py <path_to_kml_or_kmz> [-o ./output]")
        print("Running unit tests on synthetic terrain...")
        test_pond_siting_identifies_central_bowl()
        test_pond_siting_area_filter()
        test_pond_siting_rejects_linear_road_corridor()
        print("All synthetic pond siting tests passed successfully!")
