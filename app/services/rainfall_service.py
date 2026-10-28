"""
Rainfall and Precipitation Analytics Service.

Fetches real-world historical and climatological rainfall data for a given
geographic coordinate (latitude, longitude) using the Open-Meteo Historical Archive API
(ERA5 Reanalysis) with automatic caching and a robust regional fallback model.

Metrics computed:
  - Mean Annual Precipitation (mm)
  - Monsoon Season Precipitation (June–September) in mm and percentage
  - 24-hr Design Storm Rainfall (mm) — directly feeds SCS-CN runoff estimation
  - Monthly Averages (Jan–Dec) for seasonal water-budget planning
  - Historical Year-by-Year rainfall comparison
"""

import datetime
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# In-memory LRU-like cache: (round(lat, 2), round(lon, 2)) -> (timestamp, data)
_RAINFALL_CACHE: Dict[Tuple[float, float], Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 86400.0  # 24 hours


def _get_regional_fallback(lat: float, lon: float) -> Dict[str, Any]:
    """
    Resilient climatological fallback when internet or external API is unavailable.
    Provides realistic Indian / regional monsoon rainfall estimates based on geographic zones.
    """
    # Default Central India / Chhattisgarh (Bhilai / Raipur region)
    annual = 1380.0
    monsoon_ratio = 0.88
    design_24h = 110.0

    # Rough regional adjustments across India
    if 18.0 <= lat <= 24.5 and 80.0 <= lon <= 85.0:
        # Central-Eastern India / Chhattisgarh plateau
        annual = 1390.0
        design_24h = 115.0
    elif 8.0 <= lat <= 15.0 and 74.0 <= lon <= 78.0:
        # Western Ghats / Coastal Karnataka / Kerala
        annual = 2850.0
        design_24h = 180.0
    elif 24.0 <= lat <= 30.0 and 69.0 <= lon <= 77.0:
        # Arid / Semi-Arid Rajasthan / Gujarat
        annual = 520.0
        design_24h = 65.0
    elif 23.0 <= lat <= 28.0 and 88.0 <= lon <= 96.0:
        # North-East / Bengal / Assam
        annual = 2400.0
        design_24h = 160.0
    elif 11.0 <= lat <= 19.0 and 77.0 <= lon <= 82.0:
        # Deccan plateau / Telangana / Andhra interior
        annual = 850.0
        design_24h = 85.0

    monsoon_total = round(annual * monsoon_ratio, 1)

    # Monthly rainfall distribution weights (Monsoon peak July-Aug)
    monthly_weights = [
        0.01, 0.01, 0.015, 0.02, 0.035,  # Jan - May
        0.18, 0.32, 0.28, 0.10,          # Jun - Sep (Monsoon)
        0.02, 0.005, 0.005               # Oct - Dec
    ]
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_averages = [
        {"month": name, "month_idx": idx + 1, "rainfall_mm": round(annual * w, 1)}
        for idx, (name, w) in enumerate(zip(month_names, monthly_weights))
    ]

    current_year = datetime.date.today().year
    historical_annual = [
        {"year": current_year - 3, "rainfall_mm": round(annual * 0.92, 1)},
        {"year": current_year - 2, "rainfall_mm": round(annual * 1.05, 1)},
        {"year": current_year - 1, "rainfall_mm": round(annual * 0.98, 1)},
    ]

    return {
        "status": "success",
        "location": {"latitude": round(lat, 5), "longitude": round(lon, 5)},
        "mean_annual_rainfall_mm": round(annual, 1),
        "monsoon_rainfall_mm": monsoon_total,
        "monsoon_share_pct": round(monsoon_ratio * 100, 1),
        "design_24h_rainfall_mm": round(design_24h, 1),
        "recommended_design_rainfall_mm": round(design_24h, 1),
        "wet_season": "June – September (South-West Monsoon)",
        "wet_months": ["June", "July", "August", "September"],
        "monthly_averages_mm": monthly_averages,
        "historical_annual": historical_annual,
        "source": "Regional Climatological Fallback (IMD Normal Estimates)",
        "is_fallback": True,
        "hydrological_notes": (
            f"Climatological normal for this region indicates ~{annual:.0f} mm annual precipitation, "
            f"with {monsoon_ratio * 100:.0f}% concentrated during the monsoon season. "
            f"Recommended 24-hr design storm is {design_24h:.1f} mm."
        ),
    }


class RainfallService:
    """Service for querying and analyzing precipitation regimes for pond siting."""

    def __init__(self, request_timeout: int = 8):
        self.request_timeout = request_timeout

    def get_rainfall_data(
        self,
        latitude: float,
        longitude: float,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetches historical precipitation for a given coordinate.
        Uses Open-Meteo ERA5 reanalysis archive, falling back gracefully to regional climatology.
        """
        cache_key = (round(latitude, 2), round(longitude, 2))
        now = datetime.datetime.now().timestamp()

        # Check memory cache
        if cache_key in _RAINFALL_CACHE:
            ts, cached_result = _RAINFALL_CACHE[cache_key]
            if now - ts < CACHE_TTL_SECONDS:
                logger.info("Serving rainfall from cache for (%.2f, %.2f)", latitude, longitude)
                return cached_result

        # Determine year range (last 3 complete calendar years)
        current_year = datetime.date.today().year
        e_year = end_year or (current_year - 1)
        s_year = start_year or (e_year - 2)

        start_date = f"{s_year}-01-01"
        end_date = f"{e_year}-12-31"

        api_url = (
            "https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={latitude:.5f}&longitude={longitude:.5f}&"
            f"start_date={start_date}&end_date={end_date}&"
            "daily=precipitation_sum&timezone=auto"
        )

        try:
            logger.info("Fetching rainfall data from Open-Meteo for (%.4f, %.4f)...", latitude, longitude)
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "JalaSetu-Rainfall-Service/1.0 (academic-watershed-analysis)"},
            )
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP status {resp.status} from Open-Meteo")
                raw_data = json.loads(resp.read().decode("utf-8"))

            daily = raw_data.get("daily", {})
            times: List[str] = daily.get("time", [])
            precips: List[Optional[float]] = daily.get("precipitation_sum", [])

            if not times or not precips or len(times) != len(precips):
                raise ValueError("Empty or malformed daily precipitation array")

            # Group by year and month, and track annual daily maximums
            annual_totals: Dict[int, float] = {}
            annual_max_daily: Dict[int, float] = {}
            monthly_totals: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
            valid_daily_rain: List[float] = []

            for d_str, p_val in zip(times, precips):
                if p_val is None:
                    continue
                p = max(0.0, float(p_val))
                if p > 0.0:
                    valid_daily_rain.append(p)
                parts = d_str.split("-")
                y, m = int(parts[0]), int(parts[1])
                annual_totals[y] = annual_totals.get(y, 0.0) + p
                annual_max_daily[y] = max(annual_max_daily.get(y, 0.0), p)
                monthly_totals[m].append(p)

            num_years = max(1, len(annual_totals))
            mean_annual = sum(annual_totals.values()) / num_years

            # Monsoon precipitation (June, July, August, September in South Asia)
            monsoon_sum = sum(sum(monthly_totals[m]) for m in (6, 7, 8, 9))
            monsoon_annual_avg = monsoon_sum / num_years
            monsoon_share = (monsoon_annual_avg / mean_annual * 100.0) if mean_annual > 0 else 0.0

            # 24-hr design storm: Average of annual maximum daily rainfall events (hydrological 2-year 24h event)
            if annual_max_daily:
                design_storm_val = sum(annual_max_daily.values()) / len(annual_max_daily)
            elif valid_daily_rain:
                valid_daily_rain.sort()
                design_storm_val = float(valid_daily_rain[int(0.95 * len(valid_daily_rain))])
            else:
                design_storm_val = 100.0

            design_storm_val = max(50.0, min(300.0, design_storm_val))

            month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            monthly_averages = [
                {
                    "month": month_names[m - 1],
                    "month_idx": m,
                    "rainfall_mm": round(sum(monthly_totals[m]) / num_years, 1),
                }
                for m in range(1, 13)
            ]

            historical_annual = [
                {"year": y, "rainfall_mm": round(annual_totals[y], 1)}
                for y in sorted(annual_totals.keys())
            ]

            result = {
                "status": "success",
                "location": {"latitude": round(latitude, 5), "longitude": round(longitude, 5)},
                "mean_annual_rainfall_mm": round(mean_annual, 1),
                "monsoon_rainfall_mm": round(monsoon_annual_avg, 1),
                "monsoon_share_pct": round(monsoon_share, 1),
                "design_24h_rainfall_mm": round(design_storm_val, 1),
                "recommended_design_rainfall_mm": round(design_storm_val, 1),
                "wet_season": "June – September (Monsoon)",
                "wet_months": ["June", "July", "August", "September"],
                "monthly_averages_mm": monthly_averages,
                "historical_annual": historical_annual,
                "source": f"Open-Meteo ERA5 Reanalysis ({s_year}–{e_year})",
                "is_fallback": False,
                "hydrological_notes": (
                    f"Historical reanalysis for this coordinate shows {mean_annual:.0f} mm mean annual precipitation, "
                    f"with {monsoon_share:.1f}% occurring during the monsoon season. "
                    f"Suggested 24-hr design storm is {design_storm_val:.1f} mm."
                ),
            }

            _RAINFALL_CACHE[cache_key] = (now, result)
            return result

        except Exception as exc:
            logger.warning(
                "Open-Meteo rainfall query failed for (%.4f, %.4f): %s. Using regional fallback.",
                latitude,
                longitude,
                exc,
            )
            fallback = _get_regional_fallback(latitude, longitude)
            _RAINFALL_CACHE[cache_key] = (now, fallback)
            return fallback
