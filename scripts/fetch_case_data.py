from pathlib import Path
from urllib.request import urlopen, Request
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forecasting import read_routes, read_forecast, validate_dataset

PREFIX = 'https://gist.githubusercontent.com/Murkat-git/3ddc868889d3e0d37542d786c8b1aa74/raw/'
FILES = {
    'routes.csv': PREFIX + 'a934b1220da2b20d7f3eb397a7459fe78ea168ef/routes.csv',
    'seasonal_forecast.csv': PREFIX + 'seasonal_forecast.csv',
}


def main():
    blobs = {}
    for name, url in FILES.items():
        print(f'Downloading {name} ...')
        req = Request(url, headers={'User-Agent': 'ReshishAvia/1.0'})
        with urlopen(req, timeout=25) as response:
            blobs[name] = response.read(5 * 1024 * 1024 + 1)
        if len(blobs[name]) > 5 * 1024 * 1024:
            raise RuntimeError(f'{name} exceeds size limit')
    routes = read_routes(blobs['routes.csv'].decode('utf-8-sig'))
    forecast = read_forecast(blobs['seasonal_forecast.csv'].decode('utf-8-sig'))
    validate_dataset(routes, forecast)
    target = Path(__file__).resolve().parents[1] / 'data'
    target.mkdir(parents=True, exist_ok=True)
    for name, blob in blobs.items():
        (target / name).write_bytes(blob)
    print(f'Loaded {len(forecast)} flights / {len(routes)} routes from the public case.')


if __name__ == '__main__':
    main()
