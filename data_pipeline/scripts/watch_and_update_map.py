"""Watch for partial camera outputs and regenerate checkpoint map when data appears.

Runs until it finds at least one real camera feature, then invokes the map generator.
"""
import time
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def find_partial_features():
    snap_dir = ROOT / 'data' / 'snapshots'
    out_dir = ROOT / 'data' / 'output'
    # check priority output first
    pprio = out_dir / 'cameras_priority_metros.geojson'
    if pprio.exists():
        try:
            j = json.loads(pprio.read_text())
            if j.get('features'):
                return len(j.get('features'))
        except Exception:
            pass
    # check snapshot partial files
    if snap_dir.exists():
        for f in snap_dir.glob('*.partial.json'):
            try:
                j = json.loads(f.read_text())
                if j.get('features'):
                    return len(j.get('features'))
            except Exception:
                continue
    return 0


def main(poll_interval=10):
    print('Watching for partial camera outputs...')
    while True:
        n = find_partial_features()
        if n > 0:
            print(f'Found {n} features; regenerating checkpoint map')
            subprocess.run(['C:/Users/court/miniforge3/condabin/conda.bat', 'run', '-n', 'flockmap', 'python', 'data_pipeline/scripts/make_checkpoint_map.py'])
            print('Map regenerated')
            return
        time.sleep(poll_interval)


if __name__ == '__main__':
    main()
