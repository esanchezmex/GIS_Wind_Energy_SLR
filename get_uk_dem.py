"""
Download Copernicus DEM clipped to the UK boundary GeoJSON.

Tries EEA-10m (European coverage) first, then falls back to GLO-30m.
Uses Copernicus Data Space STAC: https://stac.dataspace.copernicus.eu/v1

Requires: geopandas, pystac_client, stackstac, rioxarray, xarray
Large GeoJSON: set OGR_GEOJSON_MAX_OBJ_SIZE before GDAL reads the file.
Raster reads may require CDSE OAuth2 if you get 403 — see CDSE docs.
"""
from __future__ import annotations

import os

# Allow very large GeoJSON features (UK boundary files can exceed GDAL default).
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import logging
import time
from pathlib import Path

import geopandas as gpd
import pystac_client
import rioxarray  # noqa: F401 — registers .rio on xarray
import stackstac
from shapely.geometry import box
from pystac_client.exceptions import APIError
# --- paths (script lives in repo root) ---
ROOT = Path(__file__).resolve().parent
UK_GEOJSON = ROOT / "raw_data" / "UK_Boundries.geojson"
OUT_TIF = ROOT / "processed_data" / "UK_DEM_clipped.tif"

# CDSE STAC collection IDs (not the old short names like COP-DEM-GLO-30).
COLLECTION_EEA10 = "cop-dem-eea-10-laea-tif"
COLLECTION_GLO30 = "cop-dem-glo-30-dged-cog"

STAC_URL = "https://stac.dataspace.copernicus.eu/v1"

# --- AOI controls ---
# Keep only selected UK country polygons from UK_Boundries.geojson.
# Set to [] to use all available country polygons.
AOI_COUNTRIES = ["England", "Scotland", "Wales", "Northern Ireland"]

# Buffer AOI in degrees (EPSG:4326). 0.0 means no buffer.
# Positive grows AOI, negative shrinks it slightly.
AOI_BUFFER_DEG = 0.0

# Human-readable labels for logs (STAC collection id -> product name).
COLLECTION_LABEL = {
    COLLECTION_EEA10: "Copernicus DEM EEA-10m (10 m, Europe)",
    COLLECTION_GLO30: "Copernicus DEM GLO-30 (30 m, global)",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _stac_search_with_retry(catalog, **kwargs):
    """STAC API may return 429 rate limit; brief retry."""
    delays = (2, 8, 20)
    last: Exception | None = None
    for d in delays:
        try:
            return catalog.search(**kwargs).item_collection()
        except APIError as e:
            last = e
            err = getattr(e, "args", [None])[0]
            if isinstance(err, dict) and err.get("status") == 429:
                time.sleep(d)
                continue
            raise
    assert last is not None
    raise last


def _build_aoi(uk_gdf: gpd.GeoDataFrame):
    """Build a tighter AOI geometry from selected country polygons."""
    aoi = uk_gdf
    if AOI_COUNTRIES:
        aoi = aoi[aoi["CTRY24NM"].isin(AOI_COUNTRIES)].copy()
    if aoi.empty:
        raise RuntimeError(
            "AOI filter returned no rows. Check AOI_COUNTRIES values against CTRY24NM."
        )

    # Combine to a single geometry for clipping/search.
    geom = aoi.geometry.union_all()
    if AOI_BUFFER_DEG != 0.0:
        geom = geom.buffer(AOI_BUFFER_DEG)
    return geom


def main() -> None:
    uk_gdf = gpd.read_file(UK_GEOJSON)
    uk_gdf = uk_gdf.to_crs(epsg=4326)

    uk_outline = _build_aoi(uk_gdf)
    minx, miny, maxx, maxy = uk_outline.bounds
    bbox = (float(minx), float(miny), float(maxx), float(maxy))
    logger.info("AOI countries: %s", AOI_COUNTRIES if AOI_COUNTRIES else "ALL")
    logger.info("AOI bbox: %.4f, %.4f, %.4f, %.4f", *bbox)

    catalog = pystac_client.Client.open(STAC_URL)

    items = None
    collection_used = None
    for coll in (COLLECTION_EEA10, COLLECTION_GLO30):
        try:
            # Use bbox only — sending the full UK multipolygon as `intersects` is huge and slow.
            found = _stac_search_with_retry(
                catalog,
                collections=[coll],
                bbox=bbox,
            )
        except APIError as e:
            err = getattr(e, "args", [None])[0]
            if isinstance(err, dict) and err.get("status") == 429:
                logger.warning(
                    "STAC rate limit (429). Wait a few minutes and run again, "
                    "or try from a different network."
                )
            raise
        if len(found):
            items = found
            collection_used = coll
            break
        logger.info(
            "No items for %s; trying next collection.",
            COLLECTION_LABEL.get(coll, coll),
        )

    if items is None or len(items) == 0:
        raise RuntimeError(
            "No STAC items found for the UK extent. "
            "Check bbox/collection IDs and STAC availability."
        )

    label = COLLECTION_LABEL.get(collection_used, collection_used)
    logger.info("Selected DEM source: %s", label)
    logger.info("STAC collection id: %s", collection_used)
    logger.info("STAC items matched: %d", len(items))

    # Remove tiles that don't intersect AOI to reduce I/O and memory.
    filtered_items = [
        item
        for item in items
        if item.bbox and box(*item.bbox).intersects(uk_outline)
    ]
    if filtered_items:
        logger.info(
            "Items intersecting AOI: %d of %d", len(filtered_items), len(items)
        )
        items = filtered_items

    # Mosaic in WGS84 (EEA-10 native grid is LAEA; stackstac reprojects to epsg).
    stack = stackstac.stack(items, epsg=4326, bounds=bbox)

    uk_dem = stack.rio.clip([uk_outline], crs=uk_gdf.crs, drop=True)

    OUT_TIF.parent.mkdir(parents=True, exist_ok=True)
    uk_dem.rio.to_raster(OUT_TIF)
    logger.info("Wrote %s", OUT_TIF)


if __name__ == "__main__":
    main()
