from __future__ import annotations

import os
import re
import secrets
import shutil
import sqlite3
from functools import lru_cache, wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from forecasting import (
    DataError, load_csv_files, read_forecast, read_routes, simulate, calculate,
    validate_dataset,
)
from db import connect, create_user, get_user_by_email, get_user_by_id, init_db

ROOT = Path(__file__).resolve().parent


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("APP_DATABASE", str(ROOT / "data" / "app.sqlite3")),
        DATA_FOLDER=os.environ.get("DATA_FOLDER", str(ROOT / "data")),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("HTTPS_ONLY") == "1",
        JSON_AS_ASCII=False,
    )
    base = Path(app.config["DATA_FOLDER"])
    base.mkdir(parents=True, exist_ok=True)

    database = app.config["DATABASE"]
    init_db(database)

    def current_user():
        uid = session.get("uid")
        if not uid:
            return None
        with connect(database) as conn:
            return get_user_by_id(conn, uid)

    def csrf_token():
        if not session.get("csrf"):
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def require_csrf(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            actual = request.headers.get("X-CSRF-Token", "")
            expected = csrf_token()
            if not actual or not secrets.compare_digest(actual, expected):
                return jsonify(error="Сессия обновилась. Перезагрузите страницу."), 403
            return f(*args, **kwargs)
        return wrapped

    def require_login(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user():
                return jsonify(error="Сначала войдите в аккаунт"), 401
            return f(*args, **kwargs)
        return wrapped

    @lru_cache(maxsize=32)
    def cached_load(routes_file, forecast_file, route_mtime, forecast_mtime,
                    route_size, forecast_size):
        return load_csv_files(Path(routes_file), Path(forecast_file))

    def get_dataset():
        user = current_user()
        sources = []
        if user:
            personal = base / "uploads" / str(user["id"])
            sources.append(("personal", personal / "routes.csv", personal / "forecast.csv"))
        sources.extend((
            ("real", base / "routes.csv", base / "my_forecast.csv"),
            ("real", base / "routes.csv", base / "forecast.csv"),
            ("real", base / "routes.csv", base / "seasonal_forecast.csv"),
        ))
        for kind, rp, fp in sources:
            if rp.is_file() and fp.is_file():
                route_stat, forecast_stat = rp.stat(), fp.stat()
                return (*cached_load(
                    str(rp), str(fp), route_stat.st_mtime_ns,
                    forecast_stat.st_mtime_ns, route_stat.st_size,
                    forecast_stat.st_size,
                ), kind)
        raise DataError("Не найдены routes.csv и файл прогноза в папке data/.")

    def requested_price(route):
        try:
            price = float(request.args.get("price", route["base_price"]))
        except ValueError:
            raise DataError("Цена должна быть числом") from None
        if not route["price_min"] <= price <= route["price_max"]:
            raise DataError(f"Цена должна быть от {route['price_min']:g} до {route['price_max']:g} ₽")
        return price

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.errorhandler(DataError)
    def invalid_data(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_big(error):
        return jsonify(error="Слишком большой файл. Максимум 8 МБ."), 413

    @app.route("/")
    def index():
        csrf_token()
        return render_template("index.html")

    @app.route("/scenarios")
    def scenarios_page():
        csrf_token()
        return render_template("scenarios.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        routes, forecast, kind = get_dataset()
        active = sorted({code for code, _ in forecast})
        dates = sorted({day for code, day in forecast})
        return jsonify(
            user=current_user(), csrf=csrf_token(), mode=kind,
            routes=[{
                "route": code, "name": routes[code]["name"],
                "origin": routes[code]["origin"], "destination": routes[code]["destination"],
                "basePrice": routes[code]["base_price"],
                "priceMin": routes[code]["price_min"], "priceMax": routes[code]["price_max"],
            } for code in active if code in routes],
            dates=dates, flights=len(forecast), routeCount=len(active),
            range={"from": dates[0], "to": dates[-1]},
        )

    @app.get("/api/simulate")
    def simulate_endpoint():
        routes, forecast, kind = get_dataset()
        route = (request.args.get("route") or "").strip().upper()
        day = (request.args.get("date") or "").strip()
        if route not in routes or (route, day) not in forecast:
            raise DataError("Рейс не найден. Выберите доступный маршрут и дату.")
        price = requested_price(routes[route])
        result = simulate(forecast[(route, day)], routes[route], price)
        result["mode"] = kind
        return jsonify(result)

    @app.get("/api/trends")
    def trends_endpoint():
        routes, forecast, _ = get_dataset()
        route = (request.args.get("route") or "").strip().upper()
        if route not in routes:
            raise DataError("Неизвестный маршрут")
        price = requested_price(routes[route])
        points = []
        for (route_id, day), flight in sorted(forecast.items()):
            if route_id != route:
                continue
            median = calculate(flight["bases"]["0.5"], price, routes[route], flight["seats"])
            low = calculate(flight["bases"]["0.1"], price, routes[route], flight["seats"])
            high = calculate(flight["bases"]["0.9"], price, routes[route], flight["seats"])
            points.append({"date": day, "seats": flight["seats"], "sold": median["sold"],
                           "low": low["sold"], "high": high["sold"]})
        return jsonify(route=route, points=points)

    @app.post("/api/auth/register")
    @require_csrf
    def register():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        if not 2 <= len(name) <= 60:
            raise DataError("Имя должно содержать от 2 до 60 символов")
        if not re.fullmatch(r"[^\s@]{1,80}@[^\s@]{1,100}\.[^\s@]{2,}", email):
            raise DataError("Введите корректный email")
        if len(password) < 8 or len(password) > 128:
            raise DataError("Пароль должен содержать от 8 до 128 символов")
        try:
            with connect(database) as conn:
                user_id = create_user(conn, name, email, generate_password_hash(password))
        except sqlite3.IntegrityError:
            raise DataError("Такой email уже зарегистрирован") from None
        session.clear()
        session["uid"] = user_id
        return jsonify(user=current_user(), csrf=csrf_token()), 201

    @app.post("/api/auth/login")
    @require_csrf
    def login():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        with connect(database) as conn:
            row = get_user_by_email(conn, email)
        if not row or not check_password_hash(row["password_hash"], password):
            return jsonify(error="Неверная почта или пароль"), 401
        session.clear()
        session["uid"] = row["id"]
        return jsonify(user=current_user(), csrf=csrf_token())

    @app.post("/api/auth/logout")
    @require_csrf
    def logout():
        session.clear()
        return jsonify(user=None, csrf=csrf_token())

    @app.post("/api/data/upload")
    @require_csrf
    @require_login
    def upload_data():
        routes_file = request.files.get("routes")
        forecast_file = request.files.get("forecast")
        if not routes_file or not forecast_file:
            raise DataError("Выберите routes.csv и файл прогноза")

        try:
            routes_bytes = routes_file.read()
            forecast_bytes = forecast_file.read()
            routes = read_routes(routes_bytes.decode("utf-8-sig"))
            forecast = read_forecast(forecast_bytes.decode("utf-8-sig"))
            validate_dataset(routes, forecast)
        except UnicodeDecodeError:
            raise DataError("CSV должен быть сохранён в кодировке UTF-8") from None

        user = current_user()
        upload_dir = base / "uploads" / str(user["id"])
        upload_dir.mkdir(parents=True, exist_ok=True)
        for name, content in (("routes.csv", routes_bytes), ("forecast.csv", forecast_bytes)):
            temporary = upload_dir / f".{name}.tmp"
            temporary.write_bytes(content)
            temporary.replace(upload_dir / name)
        cached_load.cache_clear()
        return jsonify(ok=True, mode="personal", flights=len(forecast), routes=len(routes))

    @app.post("/api/data/reset")
    @require_csrf
    @require_login
    def reset_data():
        user_dir = base / "uploads" / str(current_user()["id"])
        if user_dir.exists():
            shutil.rmtree(user_dir)
        cached_load.cache_clear()
        return jsonify(ok=True)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app
app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
