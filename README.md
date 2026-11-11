# Решись Авиа - прогноз спроса и динамическое ценообразование

Веб-приложение для части «Разработка», вариант C: интерфейс на HTML, CSS и JavaScript, серверные расчёты и API на Python и Flask, регистрация и загрузка ML-прогнозов из CSV.

## Возможности

- Выбор маршрута, даты и цены билета.
- Расчёт спроса, продаж, свободных мест, выручки и прибыли.
- Графики и таблицы для девяти квантилей спроса с учётом вместимости.
- Рекомендация оптимальной цены из CSV или по формуле.
- Регистрация и авторизация с хешированием паролей.
- Персональные загрузки CSV, доступные только владельцу аккаунта.

## Запуск

Требуется Python 3.10+.

```bash
cd reshish_avia_web
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Откройте http://127.0.0.1:5000. Сервис использует готовые данные и не обучает модель при запуске.

Для общих данных положите в `data/` файл `routes.csv` и прогноз: `my_forecast.csv`, `forecast.csv` или `seasonal_forecast.csv`. Если файлов несколько, используется этот порядок. Персональные данные аккаунта имеют приоритет над общими.

## Загрузка данных

Зарегистрируйтесь или войдите, затем отправьте `routes.csv` и прогноз в поля `routes` и `forecast` метода `POST /api/data/upload`. Для запроса нужен CSRF-токен из `/api/bootstrap`. Сервер проверит файлы до сохранения. Удалить персональный набор можно через `POST /api/data/reset`.

Вместо ручной подготовки общих файлов можно запустить скрипт загрузки публичного набора:

```bash
python scripts/fetch_case_data.py
```

Он скачает и проверит `routes.csv` и `seasonal_forecast.csv`.

### Формат CSV

`routes.csv`:

```csv
route,name,base_price,cost_per_passenger,price_sensitivity,price_min,price_max
```

Файл прогноза:

```csv
route,date,seats,0.1_base_demand,0.1_price,0.1_price_demand,...,0.9_base_demand,0.9_price,0.9_price_demand
```

Обязательны `route`, `date` в формате `YYYY-MM-DD`, `seats` и все девять полей `X_base_demand`. Поля `X_price` необязательны и задают рекомендуемые цены. Поддерживаются UTF-8, включая BOM, и разделители `,` или `;`.

## Расчёты

Для цены `P`, базовой цены `P0`, чувствительности спроса `b`, прогноза `D` и вместимости `S`:

```text
Желающих = max(0, D - b × (P - P0))
Купят    = min(S, Желающих)
Свободно = max(0, S - Купят)
Выручка  = P × Купят
Прибыль  = (P - cost_per_passenger) × Купят
```

На главном экране показывается медиана `0.5`; график отображает квантили `0.1–0.9`. Продажи не превышают вместимость, а расчёты сохраняют дробные значения ожидаемого спроса.

Если в CSV нет рекомендованной цены, она вычисляется с учётом диапазона цен и максимума прибыли:

```text
p* = clamp(max((cost + P0 + D/b)/2, P0 + (D-S)/b), price_min, price_max)
```

При `price_sensitivity = 0` и положительной марже оптимальна максимальная цена. Пересекающиеся квантили приводятся к неубывающему порядку.

## API

| Метод  | Адрес                                                     | Назначение                             |
| ------ | --------------------------------------------------------- | -------------------------------------- |
| `GET`  | `/api/bootstrap`                                          | Аккаунт, CSRF-токен, маршруты и даты   |
| `GET`  | `/api/simulate?route=MOW-AER&date=2026-06-12&price=12500` | Расчёт девяти сценариев                |
| `GET`  | `/api/trends?route=MOW-AER&price=12500`                   | Продажи по датам                       |
| `POST` | `/api/auth/register`                                      | Регистрация                            |
| `POST` | `/api/auth/login`                                         | Вход                                   |
| `POST` | `/api/auth/logout`                                        | Выход                                  |
| `POST` | `/api/data/upload`                                        | Загрузка CSV, требуется вход           |
| `POST` | `/api/data/reset`                                         | Удаление личных данных, требуется вход |
| `GET`  | `/health`                                                 | Проверка сервера                       |

Для всех `POST` передавайте заголовок `X-CSRF-Token` из `/api/bootstrap`. Cookie сессии браузер отправляет автоматически. Расчёты выполняются на сервере.

## Размещение

Для запуска через Gunicorn за Nginx:

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export HTTPS_ONLY=1
# При необходимости: APP_DATABASE=/persistent/app.sqlite3
# При необходимости: DATA_FOLDER=/persistent/data
gunicorn --bind 127.0.0.1:8000 --workers 1 app:app
```

Храните `SECRET_KEY` постоянным, а SQLite и пользовательские файлы - на постоянном диске.

## Структура проекта

```text
reshish_avia_web/
├── app.py
├── forecasting.py
├── db.py
├── templates/
├── static/
├── data/
├── scripts/fetch_case_data.py
├── requirements.txt
├── Procfile
└── README.md
```
