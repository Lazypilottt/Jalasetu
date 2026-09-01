"""
Demo Execution Script for Pond Catchment Analysis.

Capabilities:
  - Takes a KML/KMZ contour map file path as a CLI argument.
  - Supports two execution modes:
      1. --mode api    : Calls running FastAPI server (POST /analyzeContour) via HTTP request.
      2. --mode direct : Directly invokes app.services.pipeline.analyze_contour_file in-process.
  - Automatically falls back to direct mode if the HTTP server is not reachable.
  - Pretty-prints the structured CatchmentResponse JSON.
  - Renders and saves a comprehensive single composite PNG visualization:
      [DEM Elevation / Hillshade + Terrain Suitability Overlay + Candidate Site Markers + Catchment Boundary Polygon]

Usage:
  python scripts/demo_run.py path/to/contours.kml
  python scripts/demo_run.py path/to/contours.kmz --mode direct --output-dir ./output
  python scripts/demo_run.py path/to/contours.kml --mode api --url http://127.0.0.1:8000
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.models.schemas import CatchmentResponse
from app.services.kml_parser import KMLParserService
from app.services.dem_builder import DEMBuilderService
from app.services.terrain_analysis import TerrainAnalysisService
from app.services.pond_site import PondSiteService
from app.services.catchment_delineation import CatchmentDelineationService
from app.services.pipeline import analyze_contour_file


def run_via_api(
    file_path: Path,
    url: str = "http://127.0.0.1:8000",
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Submit contour file to the running FastAPI backend over HTTP.
    """
    import requests

    endpoint = f"{url.rstrip('/')}/analyzeContour"
    print(f"Connecting to API endpoint: {endpoint} ...")

    files = {"file": (file_path.name, open(file_path, "rb"), "application/octet-stream")}
    data = {}
    if params:
        for k, v in params.items():
            if v is not None:
                data[k] = str(v)

    try:
        response = requests.post(endpoint, files=files, data=data, timeout=120)
    except requests.exceptions.ConnectionError:
        print(f"⚠️  Could not connect to FastAPI server at {url}.")
        return None
    except Exception as e:
        print(f"⚠️  HTTP request error: {e}")
        return None
    finally:
        files["file"][1].close()

    if response.status_code == 200:
        return response.json()
    else:
        print(f"API returned HTTP {response.status_code}: {response.text}")
        try:
            return response.json()
        except Exception:
            return {"error": response.text, "status_code": response.status_code}


def run_via_direct_pipeline(
    file_path: Path,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute python pipeline in-process directly.
    """
    print("Executing in-process pipeline (analyze_contour_file)...")
    response_obj = analyze_contour_file(file_path, params=params)
    return response_obj.model_dump()


def pretty_print_response(data: Dict[str, Any]):
    """
    Format and pretty-print the CatchmentResponse JSON with structured sections.
    """
    print("\n" + "=" * 80)
    print("                      CATCHMENT ANALYSIS REPORT                      ")
    print("=" * 80)

    status_str = data.get("status", "unknown").upper()
    print(f"Status: {status_str}")
    if data.get("message"):
        print(f"Message: {data['message']}")

    # 1. Input Summary
    inp = data.get("input_summary")
    if inp:
        print("\n--- 1. Input Dataset & DEM Metadata ---")
        print(f"  • Extracted Contours : {inp.get('num_contours')} lines")
        print(f"  • Elevation Range    : {inp.get('elevation_min', 0):.2f}m to {inp.get('elevation_max', 0):.2f}m")
        print(f"  • DEM Resolution     : {inp.get('dem_resolution_m', 0):.2f} meters/cell")
        print(f"  • Projected UTM CRS  : {inp.get('utm_crs', 'N/A')}")

    # 2. Recommended Site
    rec = data.get("recommended_site")
    if rec:
        print("\n--- 2. Recommended Pond Location (Rank #1) ---")
        print(f"  • Site Identifier    : {rec.get('site_id')}")
        print(f"  • WGS84 Coordinates  : {rec.get('latitude', 0):.6f}° N, {rec.get('longitude', 0):.6f}° E")
        print(f"  • Suitability Score  : {rec.get('suitability_score', 0):.1f} / 100")
        print(f"  • Excavation Area    : {rec.get('area_m2', 0):,.1f} m² ({rec.get('area_m2', 0)/10000:.3f} ha)")
        print(f"  • Mean Elevation     : {rec.get('elevation_m', 0):.2f} m")
        print(f"  • Mean Ground Slope  : {rec.get('slope_deg', 0):.2f}°")

    # 3. Alternative Sites
    alts = data.get("alternative_sites", [])
    if alts:
        print(f"\n--- 3. Alternative Candidate Sites ({len(alts)} found) ---")
        for a in alts:
            print(
                f"  • #{a.get('rank', '?')} {a.get('site_id')}: Score {a.get('suitability_score', 0):.1f} | "
                f"Area {a.get('area_m2', 0):,.0f}m² | Elev {a.get('elevation_m', 0):.1f}m | "
                f"Slope {a.get('slope_deg', 0):.1f}° | ({a.get('latitude', 0):.5f}°N, {a.get('longitude', 0):.5f}°E)"
            )

    # 4. Catchment Basin
    cat = data.get("catchment")
    if cat:
        elev_range = cat.get("elevation_range_m", {})
        print("\n--- 4. Delineated Upstream Catchment ---")
        print(f"  • Contributing Area  : {cat.get('area_m2', 0):,.1f} m² ({cat.get('area_hectares', 0):.3f} hectares)")
        print(f"  • Mean Basin Slope   : {cat.get('average_slope_deg', 0):.2f}°")
        print(f"  • Elevation Range    : {elev_range.get('min_m', 0):.2f}m to {elev_range.get('max_m', 0):.2f}m (Relief: {elev_range.get('relief_m', 0):.2f}m)")
        print(f"  • Routing Engine     : {cat.get('delineation_method')}")

    # 5. Processing Notes
    notes = data.get("processing_notes", [])
    if notes:
        print("\n--- 5. Processing Notes & Execution Logs ---")
        for n in notes:
            print(f"  [info] {n}")

    print("=" * 80 + "\n")


def generate_composite_visualization(
    file_path: Path,
    response_data: Dict[str, Any],
    output_png_path: Path,
):
    """
    Generate a high-resolution single-page composite plot showing:
      - Panel 1: Topographic DEM Shaded Relief with Original Contours + Catchment Boundary Overlay
      - Panel 2: Terrain Suitability Heatmap (0-100) with Candidate Pond Site Markers (#1, #2...)
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    output_png_path.parent.mkdir(parents=True, exist_ok=True)

    print("Generating comprehensive visual summary plot...")

    # Run internal services to get spatial grids for plotting
    kml_parser = KMLParserService()
    gdf = kml_parser.parse(file_path)

    dem_builder = DEMBuilderService()
    dem_res_override = response_data.get("input_summary", {}).get("dem_resolution_m")
    dem_data = dem_builder.build_dem(gdf, resolution=dem_res_override)

    terrain_service = TerrainAnalysisService()
    analysis = terrain_service.analyze_terrain(dem_data)

    pond_service = PondSiteService()
    siting = pond_service.identify_candidate_sites(analysis, top_n=5)

    catchment_service = CatchmentDelineationService()
    catch_res = None
    if siting.top_candidate:
        catch_res = catchment_service.delineate(dem_data, siting.top_candidate)

    minx, miny, maxx, maxy = dem_data.bounds
    extent = [minx, maxx, miny, maxy]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 9), constrained_layout=True)

    # =========================================================================
    # Panel 1: Shaded Relief DEM + Original Contours + Catchment Basin Boundary
    # =========================================================================
    ls = LightSource(azdeg=315, altdeg=45)
    rgb_dem = ls.shade(
        dem_data.array,
        cmap=plt.cm.terrain,
        blend_mode="overlay",
        vert_exag=1.5,
        dx=dem_data.resolution,
        dy=dem_data.resolution,
    )
    ax1.imshow(rgb_dem, extent=extent, origin="upper")

    # Plot input contour lines (sample subset if large to keep render sharp)
    gdf_utm, _ = kml_parser.to_utm(gdf)
    sample_gdf = gdf_utm if len(gdf_utm) <= 500 else gdf_utm.iloc[::max(1, len(gdf_utm)//400)]
    sample_gdf.plot(ax=ax1, color="black", linewidth=0.5, alpha=0.4, label="Contour Lines")

    # Overlay Delineated Catchment Basin
    if catch_res is not None and np.any(catch_res.catchment_mask):
        catch_mask_vis = np.where(catch_res.catchment_mask, 1.0, np.nan)
        ax1.imshow(catch_mask_vis, extent=extent, origin="upper", cmap="Blues_r", alpha=0.4)
        ax1.contour(
            catch_res.catchment_mask.astype(int),
            levels=[0.5],
            colors="#0055FF",
            linewidths=2.2,
            extent=extent,
            origin="upper",
        )
        # Snapped stream pour point
        ax1.scatter(
            catch_res.snapped_pour_point_utm[0],
            catch_res.snapped_pour_point_utm[1],
            color="#FFD700",
            edgecolors="black",
            marker="*",
            s=250,
            zorder=12,
            label=f"Catchment Pour Point ({catch_res.area_ha:.2f} ha)",
        )

    cat_info = response_data.get("catchment") or {}
    ax1.set_title(
        f"A. Topographic Elevation DEM & Delineated Watershed Basin\n"
        f"Catchment Area: {cat_info.get('area_hectares', 0):.2f} ha | Relief: {dem_data.min_elevation:.1f}m - {dem_data.max_elevation:.1f}m",
        fontsize=13,
        fontweight="bold",
    )
    ax1.set_xlabel("UTM Easting (m)")
    ax1.set_ylabel("UTM Northing (m)")
    ax1.grid(True, linestyle="--", alpha=0.3)
    ax1.legend(loc="upper right", framealpha=0.9)

    # =========================================================================
    # Panel 2: Terrain Suitability Heatmap + Pond Candidate Site Markers
    # =========================================================================
    shaded_suitability = ls.shade(
        analysis.suitability_score,
        cmap=plt.cm.viridis,
        blend_mode="overlay",
        vert_exag=1.2,
        dx=dem_data.resolution,
        dy=dem_data.resolution,
    )
    ax2.imshow(shaded_suitability, extent=extent, origin="upper")

    cbar = fig.colorbar(
        plt.cm.ScalarMappable(norm=plt.Normalize(vmin=0, vmax=100), cmap=plt.cm.viridis),
        ax=ax2,
        fraction=0.046,
        pad=0.04,
    )
    cbar.set_label("Pond Siting Suitability Score (0-100)", fontsize=11, fontweight="bold")

    # Plot ranked candidate pond sites
    colors = ["#FF2D55", "#FF9500", "#FFCC00", "#34C759", "#007AFF"]
    for i, cand in enumerate(siting.candidates[:5]):
        col = colors[i % len(colors)]
        is_top = (cand.rank == 1)

        ax2.scatter(
            cand.utm_x,
            cand.utm_y,
            marker="*" if is_top else "o",
            s=220 if is_top else 120,
            color=col,
            edgecolors="white",
            linewidths=1.8,
            zorder=10,
            label=f"#{cand.rank} {cand.site_id.upper()} (Score: {cand.mean_suitability:.1f})",
        )

        label_box = (
            f"#{cand.rank} {cand.site_id.upper()}\n"
            f"Score: {cand.mean_suitability:.1f}\n"
            f"Area: {cand.area_m2:,.0f}m²\n"
            f"Slope: {cand.mean_slope_deg:.1f}°"
        )
        ax2.annotate(
            label_box,
            xy=(cand.utm_x, cand.utm_y),
            xytext=(15, 15),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.35", fc="black", ec=col, lw=1.5, alpha=0.85),
            fontsize=9,
            fontweight="bold",
            color="white",
            arrowprops=dict(arrowstyle="->", color=col, lw=1.5),
            zorder=12,
        )

    rec_site = response_data.get("recommended_site") or {}
    ax2.set_title(
        f"B. Pond Siting Suitability & Ranked Candidate Excavation Sites\n"
        f"Top Recommended Site #{rec_site.get('rank', 1)}: Score {rec_site.get('suitability_score', 0):.1f}/100 "
        f"({rec_site.get('area_m2', 0):,.0f} m²)",
        fontsize=13,
        fontweight="bold",
    )
    ax2.set_xlabel("UTM Easting (m)")
    ax2.set_ylabel("UTM Northing (m)")
    ax2.grid(True, linestyle="--", alpha=0.3)
    ax2.legend(loc="upper right", framealpha=0.9)

    fig.suptitle(
        f"Pond Catchment Analysis Demo Summary — {file_path.name} ({dem_data.crs})",
        fontsize=16,
        fontweight="bold",
    )

    plt.savefig(output_png_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    print(f"✅ Saved demo composite visualization plot to: {output_png_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Demo script: Run full pond catchment analysis via API or direct pipeline and save visual PNG."
    )
    parser.add_argument("file_path", help="Path to sample KML or KMZ contour map file")
    parser.add_argument(
        "--mode",
        choices=["api", "direct"],
        default="api",
        help="Execution mode: 'api' (HTTP POST to running server) or 'direct' (in-process python). Default: 'api'",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="FastAPI server URL (default: http://127.0.0.1:8000)")
    parser.add_argument("-o", "--output-dir", default="./output", help="Directory to save JSON report & visualization PNG")
    parser.add_argument("--dem-resolution", type=float, default=None, help="Override DEM grid resolution in meters")
    parser.add_argument("--ideal-slope", type=float, default=3.0, help="Ideal slope threshold in degrees (default: 3.0)")
    parser.add_argument("--max-slope", type=float, default=8.0, help="Max slope threshold in degrees (default: 8.0)")
    parser.add_argument("--min-area", type=float, default=200.0, help="Minimum pond area in m² (default: 200.0)")
    parser.add_argument("--suitability-threshold", type=float, default=60.0, help="Suitability score threshold (default: 60.0)")

    args = parser.parse_args()

    input_file = Path(args.file_path).resolve()
    if not input_file.exists():
        print(f"Error: File not found at '{args.file_path}'")
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "dem_resolution_m": args.dem_resolution,
        "ideal_slope_deg": args.ideal_slope,
        "max_slope_deg": args.max_slope,
        "min_pond_area_m2": args.min_area,
        "suitability_threshold": args.suitability_threshold,
    }

    response_data = None

    # Execute based on mode
    if args.mode == "api":
        response_data = run_via_api(input_file, url=args.url, params=params)
        if response_data is None:
            print("🔄 Falling back to in-process direct execution...")
            response_data = run_via_direct_pipeline(input_file, params=params)
    else:
        response_data = run_via_direct_pipeline(input_file, params=params)

    if not response_data or "error" in response_data:
        print(f"Analysis failed: {response_data}")
        sys.exit(1)

    # 1. Pretty print response
    pretty_print_response(response_data)

    # 2. Save JSON Response
    json_path = out_dir / f"{input_file.stem}_analysis_response.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(response_data, f, indent=2)
    print(f"✅ Saved JSON response to: {json_path}")

    # 3. Generate and save composite visualization
    viz_png_path = out_dir / f"{input_file.stem}_demo_visualization.png"
    try:
        generate_composite_visualization(input_file, response_data, viz_png_path)
    except Exception as e:
        print(f"⚠️  Could not generate composite visualization: {e}")


if __name__ == "__main__":
    main()
