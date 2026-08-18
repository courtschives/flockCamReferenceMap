"""Helpers to download and prepare Census TIGER county geometries.

Usage:
  from data_pipeline.utils.tiger_counties import download_and_prepare
  download_and_prepare(output_path='data/tiger_counties.geojson')
"""
import requests
import zipfile
import io
from pathlib import Path
import geopandas as gpd

# Cartographic boundary file (generalized to 20m resolution) instead of the
# full-resolution TIGER/Line file. The full TIGER county shapefile carries
# survey-grade coastline/boundary detail (~350MB as GeoJSON for 3,235
# counties) which is unusable for a web map and was the source of the
# Jinja2/browser MemoryError. The cartographic boundary file is pre-simplified
# by the Census Bureau specifically for thematic mapping (~1MB compressed).
TIGER_COUNTY_ZIP = 'https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_20m.zip'

def download_and_prepare(output_path=None):
    repo_root = Path(__file__).resolve().parents[2]
    if output_path is None:
        output_path = repo_root / 'data' / 'tiger_counties.geojson'
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print('Downloading generalized county cartographic boundaries (~1MB compressed)')
    resp = requests.get(TIGER_COUNTY_ZIP, stream=True)
    resp.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    # geopandas can read directly from a zipfile path but we'll extract to a tmp dir
    tmpdir = output_path.parent / 'tmp_tiger'
    if tmpdir.exists():
        for f in tmpdir.iterdir():
            f.unlink()
    else:
        tmpdir.mkdir(parents=True)
    z.extractall(path=str(tmpdir))
    # find the shapefile (.shp)
    shp = None
    for p in tmpdir.iterdir():
        if p.suffix.lower() == '.shp':
            shp = p
            break
    if shp is None:
        raise RuntimeError('Downloaded TIGER zip does not contain a .shp')
    gdf = gpd.read_file(str(shp))
    # ensure GEOID column exists
    if 'GEOID' not in gdf.columns and 'STATEFP' in gdf.columns and 'COUNTYFP' in gdf.columns:
        gdf['GEOID'] = gdf['STATEFP'].astype(str).str.zfill(2) + gdf['COUNTYFP'].astype(str).str.zfill(3)
    gdf = gdf.to_crs(epsg=4326)
    gdf.to_file(str(output_path), driver='GeoJSON')
    # cleanup
    for f in tmpdir.iterdir():
        f.unlink()
    tmpdir.rmdir()
    print(f'Wrote counties GeoJSON to {output_path}')
    return output_path
