from __future__ import annotations

import csv
import io
import math
from datetime import date
from pathlib import Path

QUANTILES = tuple(f"0.{i}" for i in range(1, 10))
REQUIRED_ROUTES = (
    "route", "name", "base_price", "price_sensitivity", "price_min",
    "price_max", "cost_per_passenger",
)
REQUIRED_FORECAST = ("route", "date", "seats") + tuple(f"{q}_base_demand" for q in QUANTILES)
MAX_ROWS = 3000


class DataError(ValueError):
    pass


def _number(value, label: str) -> float:
    try:
        n = float(str(value).strip().replace(" ", ""))
    except (ValueError, TypeError):
        raise DataError(f"Некорректное число в поле {label}") from None
    if not math.isfinite(n):
        raise DataError(f"Значение {label} должно быть конечным числом")
    return n


def _reader(content: str, required: tuple[str, ...]):
    if not content.strip():
        raise DataError("CSV пустой")
    first = content[:2048]
    try:
        delimiter = csv.Sniffer().sniff(first, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), delimiter=delimiter)
    if not reader.fieldnames:
        raise DataError("В CSV нет заголовков")
    reader.fieldnames = [s.strip().lstrip("\ufeff") for s in reader.fieldnames]
    missing = [col for col in required if col not in reader.fieldnames]
    if missing:
        raise DataError("В CSV отсутствуют столбцы: " + ", ".join(missing[:8]))
    return reader


def read_routes(content: str) -> dict[str, dict]:
    result = {}
    reader = _reader(content, REQUIRED_ROUTES)
    for index, r in enumerate(reader, 2):
        if index > MAX_ROWS + 1:
            raise DataError("Слишком много строк в routes.csv")
        code = (r["route"] or "").strip().upper()
        name = (r["name"] or "").strip()
        if not code or not name or len(name) > 120:
            raise DataError(f"Строка {index}: некорректный маршрут или название")
        if code in result:
            raise DataError(f"Дублирующийся маршрут {code} в routes.csv")
        data = {field: _number(r[field], field) for field in REQUIRED_ROUTES if field not in ("route", "name")}
        if data["base_price"] <= 0 or data["price_min"] <= 0 or data["price_max"] < data["price_min"]:
            raise DataError(f"Строка {index}: неверные границы цены")
        if not data["price_min"] <= data["base_price"] <= data["price_max"]:
            raise DataError(f"Строка {index}: базовая цена вне диапазона")
        if data["price_sensitivity"] < 0 or data["cost_per_passenger"] < 0:
            raise DataError(f"Строка {index}: коэффициент и расходы не могут быть отрицательными")
        origin_code, _, dest_code = code.partition("-")
        origin, dest = origin_code, dest_code or code
        for sep in (" \u2014 ", " – ", " - ", " → "):
            if sep in name:
                origin, dest = [part.strip() for part in name.split(sep, 1)]
                break
        result[code] = {"route": code, "name": name, "origin": origin, "destination": dest, **data}
    if not result:
        raise DataError("routes.csv не содержит маршрутов")
    return result


def read_forecast(content: str) -> dict[tuple[str, str], dict]:
    result = {}
    reader = _reader(content, REQUIRED_FORECAST)
    for index, r in enumerate(reader, 2):
        if index > MAX_ROWS + 1:
            raise DataError("Слишком много строк в файле прогноза")
        route = (r["route"] or "").strip().upper()
        day = (r["date"] or "").strip()
        try:
            parsed_day = date.fromisoformat(day)
        except ValueError:
            raise DataError(f"Строка {index}: дата должна быть в формате YYYY-MM-DD") from None
        if parsed_day.isoformat() != day:
            raise DataError(f"Строка {index}: дата должна быть в формате YYYY-MM-DD")
        if not route:
            raise DataError(f"Строка {index}: отсутствует маршрут")
        seats_float = _number(r["seats"], "seats")
        if seats_float < 0 or not seats_float.is_integer():
            raise DataError(f"Строка {index}: seats должно быть целым неотрицательным числом")
        bases = []
        rec_prices = {}
        for q in QUANTILES:
            base = _number(r[f"{q}_base_demand"], f"{q}_base_demand")
            bases.append(max(0.0, base))
            col = f"{q}_price"
            if col in r and r[col] not in (None, ""):
                rec_prices[q] = _number(r[col], col)
        bases = [max(bases[:i + 1]) for i in range(len(bases))]
        key = (route, day)
        if key in result:
            raise DataError(f"Строка {index}: повторяется рейс {route} {day}")
        result[key] = {
            "route": route, "date": day, "seats": int(seats_float),
            "bases": dict(zip(QUANTILES, bases)), "recommended_prices": rec_prices,
        }
    if not result:
        raise DataError("Файл прогноза не содержит рейсов")
    return result


def validate_dataset(routes: dict, forecast: dict) -> None:
    missing = sorted({r for r, _ in forecast} - set(routes))
    if missing:
        raise DataError("В routes.csv не найдены маршруты: " + ", ".join(missing))
    if not forecast:
        raise DataError("Нет прогнозов")
    for flight in forecast.values():
        for quantile, price in flight["recommended_prices"].items():
            route = routes[flight["route"]]
            flight["recommended_prices"][quantile] = min(
                route["price_max"], max(route["price_min"], price)
            )


def calculate(base_demand: float, price: float, route: dict, seats: int) -> dict:
    willing = max(0.0, base_demand - route["price_sensitivity"] * (price - route["base_price"]))
    sold = min(float(seats), willing)
    return {"willing": round(willing, 3), "sold": round(sold, 3),
            "available": round(max(0.0, seats - sold), 3),
            "revenue": round(sold * price, 2),
            "profit": round(sold * (price - route["cost_per_passenger"]), 2)}


def optimal_price(demand_base: float, route: dict, seats: int) -> float:
    b = route["price_sensitivity"]
    p0 = route["base_price"]
    cost = route["cost_per_passenger"]
    if b <= 0:
        return route["price_max"]
    top = (cost + p0 + max(0.0, demand_base) / b) / 2.0
    full = p0 + (max(0.0, demand_base) - seats) / b
    return max(route["price_min"], min(route["price_max"], max(top, full)))


def simulate(flight: dict, route: dict, price: float) -> dict:
    if not math.isfinite(price) or price < route["price_min"] or price > route["price_max"]:
        raise DataError(f"Цена должна быть от {route['price_min']:g} до {route['price_max']:g} ₽")
    scenarios = []
    for q in QUANTILES:
        base = flight["bases"][q]
        stats = calculate(base, price, route, flight["seats"])
        rec = flight["recommended_prices"].get(q, optimal_price(base, route, flight["seats"]))
        scenarios.append({"q": q, "baseDemand": round(base, 3),
                          "recommendedPrice": round(rec, 2), **stats})
    med = scenarios[4]
    cost = route["cost_per_passenger"]
    med_rec_price = med["recommendedPrice"]
    med_at_recommended = calculate(flight["bases"]["0.5"], med_rec_price, route, flight["seats"])
    return {
        "route": flight["route"], "routeName": route["name"], "date": flight["date"],
        "seats": flight["seats"], "price": price,
        "basePrice": route["base_price"], "priceMin": route["price_min"], "priceMax": route["price_max"],
        "costPerPassenger": cost, "sensitivity": route["price_sensitivity"],
        "median": med, "scenarios": scenarios,
        "recommended": {"price": med_rec_price, **med_at_recommended},
        "interval": [scenarios[0]["willing"], scenarios[-1]["willing"]],
    }


def load_csv_files(route_path: Path, forecast_path: Path) -> tuple[dict, dict]:
    try:
        routes_text = route_path.read_text(encoding="utf-8-sig")
        forecast_text = forecast_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise DataError("CSV должен быть сохранён в кодировке UTF-8") from None
    routes = read_routes(routes_text)
    forecast = read_forecast(forecast_text)
    validate_dataset(routes, forecast)
    return routes, forecast
