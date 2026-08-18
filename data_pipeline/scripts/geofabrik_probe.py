"""Download the California Geofabrik OSM extract and test ALPR filtering.

This validates the local-extract approach for a real OSM snapshot without
relying on Overpass rate-limited queries.
"""
from pathlib import Path
import requests

from pyrosm import OSM

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
PBF_PATH = DATA_DIR / 'california-latest.osm.pbf'
OUT_PATH = ROOT / 'data' / 'output' / 'geofabrik_probe.geojson'
URL = 'https://download.geofabrik.de/north-america/us/california-latest.osm.pbf'


def download_if_missing():
    if PBF_PATH.exists():
        print(f'Using existing extract: {PBF_PATH} ({PBF_PATH.stat().st_size} bytes)')
        return
    print(f'Downloading {URL} -> {PBF_PATH}')
    resp = requests.get(URL, stream=True, timeout=120)
    resp.raise_for_status()
    with PBF_PATH.open('wb') as f:
        total = 0
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)
                print(f'downloaded {total} bytes', end='\r')
    print('')
    print(f'Download complete: {PBF_PATH} ({PBF_PATH.stat().st_size} bytes)')


def main():
    download_if_missing()
    osm = OSM(str(PBF_PATH))
    print('Opening OSM extract...')
    gdf = osm.get_pois(
        custom_filter={'surveillance:type': 'ALPR'},
        extra_attributes=['surveillance:type', 'camera:type', 'amenity', 'operator', 'name'],
    )
    print('Feature count:', len(gdf))
    print(gdf.head().to_string())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(OUT_PATH), driver='GeoJSON')
    print(f'Wrote {len(gdf)} points to {OUT_PATH}')


if __name__ == '__main__':
    main()
