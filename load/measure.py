"""Замерщик времени отклика — инструмент ДЗ 1, подраздел 2.5.

Обходит операции контракта, повторяет запрос N раз после прогрева
и печатает медиану, 95-й процентиль и максимум по заголовку
X-Response-Time-ms. Первый прогон каждого адреса отбрасывается —
это прогрев (кеши базы и пул соединений ещё холодные).

    python load/measure.py                       # все операции, demo
    python load/measure.py --repeats 30          # больше повторов
    python load/measure.py --url /summary        # один адрес

Печатает и JSON в stdout (последняя строка) — его подхватывает отчёт.
"""
import argparse
import json
import os
import statistics
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import quote, urlencode

BASE = os.environ.get("MEASURE_BASE", "http://127.0.0.1:8080")

PAGES = [
    ("Главная (услуги)", "/"),
    ("Специалисты, стр. 1", "/specialists"),
    ("Специалисты, фильтр", "/specialists?speciality=%D1%82%D0%B5%D1%80%D0%B0%D0%BF%D0%B5%D0%B2%D1%82"),
    ("Карточка специалиста", "/specialists/3"),
    ("Свободные слоты", "/slots?service=2"),
    ("Мои записи, стр. 1", "/appointments"),
    ("Сводка (30 дней)", "/summary"),
]


def measure(base, pages, login, password, repeats):
    jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar))
    opener.open(base + "/login")
    opener.open(base + "/login",
                data=urlencode({"login": login, "password": password}).encode())
    # Прогрев — две полные проходки по всем страницам: кеш PostgreSQL
    # общий, и замер одной страницы сразу после наполнения/другой
    # тяжёлой страницы даёт ×5 к реальному времени.
    for _ in range(2):
        for _, warm_path in pages:
            opener.open(base + warm_path, timeout=120).read()
    print("условия: %s, учётная запись %s, повторов %d (плюс прогрев)"
          % (base, login, repeats))
    print("%-26s %10s %10s %10s %12s"
          % ("операция", "p50, мс", "p95, мс", "макс, мс", "ответ, байт"))
    results = {}
    for name, path in pages:
        times, size = [], 0
        for attempt in range(repeats + 1):
            with opener.open(base + path, timeout=120) as response:
                size = len(response.read())
                t = float(response.headers.get("X-Response-Time-ms", 0))
            if attempt:
                times.append(t)
        p95_idx = min(int(len(times) * 0.95), len(times) - 1)
        row = {
            "p50": round(statistics.median(times), 1),
            "p95": round(sorted(times)[p95_idx], 1),
            "max": round(max(times), 1),
            "bytes": size,
        }
        results[name] = row
        print("%-26s %10.1f %10.1f %10.1f %12d"
              % (name, row["p50"], row["p95"], row["max"], size))
    print("JSON " + json.dumps(results, ensure_ascii=False))


def normalize(url):
    if url.startswith("http"):
        return url
    url = url if url.startswith("/") else "/" + url
    return quote(url, safe="/?=&%:")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="один адрес вместо списка")
    parser.add_argument("--user", default="demo")
    parser.add_argument("--password", default="demo")
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    pages = [(args.url, normalize(args.url))] if args.url else PAGES
    measure(BASE, pages, args.user, args.password, args.repeats)


if __name__ == "__main__":
    main()
