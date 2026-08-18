from pathlib import Path
import json
from datetime import datetime

def main():
    repo = Path(__file__).resolve().parents[2]
    src = repo / 'data' / 'output' / 'cameras_sample.geojson'
    if not src.exists():
        print('No sample found at', src)
        return
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    snap_dir = repo / 'data' / 'snapshots'
    snap_dir.mkdir(parents=True, exist_ok=True)
    dst = snap_dir / f'cameras_snapshot_{ts}.geojson'
    manifest = snap_dir / f'cameras_snapshot_{ts}.manifest.json'
    dst.write_text(src.read_text())
    m = {'created_at': ts, 'source': 'synthetic_sample_fallback', 'file': str(dst.relative_to(repo))}
    manifest.write_text(json.dumps(m, indent=2))
    print('Wrote snapshot', dst)

if __name__ == '__main__':
    main()
