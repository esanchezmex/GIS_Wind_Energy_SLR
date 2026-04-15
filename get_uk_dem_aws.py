"""
Download Copernicus GLO-30 DEM from public AWS STAC and clip to UK AOI.

This avoids CDSE/WAF throttling by using Earth Search STAC:
  https://earth-search.aws.element84.com/v1
Collection:
  cop-dem-glo-30

Example:
  .venv/bin/python get_uk_dem_aws.py --countries England,Scotland
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import geopandas as gpd
import pystac_client
import rioxarray
from rioxarray.merge import merge_arrays
from shapely.geometry import mapping

# UK boundary file is large; raise GDAL parser limit.
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

ROOT = Path(__file__).resolve().parent
UK_GEOJSON = ROOT / "raw_data" / "UK_Boundries.geojson"
OUT_DEFAULT = ROOT / "processed_data" / "UK_DEM_AWS_GLO30.tif"

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "cop-dem-glo-30"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download + clip Copernicus GLO-30 DEM from public AWS.",
    )
    parser.add_argument(
        "--countries",
        type=str,
        default="England,Scotland,Wales,Northern Ireland",
        help=(
            "Comma-separated CTRY24NM values in UK_Boundries.geojson. "
            "Use '' (empty string) to use all polygons."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT_DEFAULT,
        help=f"Output GeoTIFF path (default: {OUT_DEFAULT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only query and report matching tiles; do not download/write raster.",
    )
    return parser.parse_args()


def _s3_to_https(href: str) -> str:
    """Convert s3://copernicus-dem-30m/key to public HTTPS URL."""
    if href.startswith("s3://copernicus-dem-30m/"):
        key = href.removeprefix("s3://copernicus-dem-30m/")
        return f"https://copernicus-dem-30m.s3.amazonaws.com/{key}"
    return href


def build_aoi(gdf: gpd.GeoDataFrame, countries_raw: str):
    countries = [x.strip() for x in countries_raw.split(",") if x.strip()]
    if countries:
        gdf = gdf[gdf["CTRY24NM"].isin(countries)].copy()
    if gdf.empty:
        raise RuntimeError(
            "AOI is empty after country filter. Check --countries against CTRY24NM."
        )
    geom = gdf.geometry.union_all()
    return gdf, geom


def main() -> int:
    args = parse_args()

    uk_gdf = gpd.read_file(UK_GEOJSON).to_crs(4326)
    aoi_gdf, aoi_geom = build_aoi(uk_gdf, args.countries)
    minx, miny, maxx, maxy = aoi_geom.bounds
    bbox = (float(minx), float(miny), float(maxx), float(maxy))

    logger.info("STAC source: %s", STAC_URL)
    logger.info("Collection: %s", COLLECTION)
    logger.info(
        "AOI countries: %s",
        [x.strip() for x in args.countries.split(",") if x.strip()] or "ALL",
    )
    logger.info("AOI bbox: %.4f, %.4f, %.4f, %.4f", *bbox)

    catalog = pystac_client.Client.open(STAC_URL)
    items = catalog.search(collections=[COLLECTION], bbox=bbox).item_collection()
    if not items:
        raise RuntimeError("No DEM tiles found for this AOI.")

    logger.info("Matched tiles: %d", len(items))
    if args.dry_run:
        return 0

    rasters = []
    for item in items:
        asset = item.assets.get("data")
        if asset is None:
            continue
        href = _s3_to_https(asset.href)
        logger.info("Reading tile: %s", item.id)
        da = rioxarray.open_rasterio(href, masked=True).squeeze(drop=True)
        rasters.append(da)

    if not rasters:
        raise RuntimeError("No readable raster assets found in matched items.")

    logger.info("Merging %d tiles...", len(rasters))
    merged = merge_arrays(rasters)
    clipped = merged.rio.clip([mapping(aoi_geom)], aoi_gdf.crs, drop=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    clipped = clipped.astype("float32")
    clipped.rio.to_raster(
        args.output,
        compress="LZW",
        tiled=True,
        predictor=2,
        BIGTIFF="IF_SAFER",
    )
    logger.info("Wrote %s", args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

