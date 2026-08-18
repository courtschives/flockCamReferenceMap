import requests

endpoints = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://lz4.overpass-api.de/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
]
query = """[out:json];
node[\"surveillance:type\"=\"ALPR\"](37.75,-122.45,37.80,-122.39);
out tags;"""

for url in endpoints:
    try:
        r = requests.post(
            url,
            data={'data': query},
            headers={'User-Agent': 'FlockMap/1.0', 'Accept': 'application/json'},
            timeout=60,
        )
        print('URL:', url)
        print('STATUS:', r.status_code)
        print(r.text[:200])
        print('---')
    except Exception as exc:
        print('URL:', url)
        print('ERROR:', type(exc).__name__, exc)
        print('---')
