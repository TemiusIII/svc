"""Разложение времени операции по слоям: код приложения против базы.

Инструмент ДЗ 1, подраздел 2.6 — по образцу sloi.py второй лабораторной.

Порядок: прогревочный визит (в статистику не попадает), сброс счётчика,
ровно один измеряемый визит, чтение счётчика и заголовка X-Response-Time-ms.

Счётчик — собственные отметки времени вокруг обращений к базе
(метод dbstats.attach на движке), включается переменной DB_STATS=1.
"""
import argparse
import json
import os
import statistics
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import quote, urlencode

BASE = os.environ.get("MEASURE_BASE", "http://127.0.0.1:8080")


def odin_vizit(base, path, login, password, repeats):
    """Возвращает список строк (total_ms, db_ms, queries) по повторам."""
    rows = []
    for _ in range(repeats):
        # Свежая сессия на каждый повтор: счётчик обнуляется запросом.
        jar = CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        opener.open(base + "/login")
        opener.open(base + "/login",
                    data=urlencode({"login": login, "password": password})
                    .encode())
        with opener.open(base + path, timeout=120) as response:
            body = response.read().decode()
            total = float(response.headers.get("X-Response-Time-ms", 0))
        try:
            stats = json.loads(response.headers.get("X-DB-Stats", "{}"))
        except json.JSONDecodeError:
            stats = {}
        rows.append((total, stats.get("db_ms", 0), stats.get("queries", 0)))
        _ = body
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="/summary")
    parser.add_argument("--user", default="demo")
    parser.add_argument("--password", default="demo")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    path = normalize(args.url)
    rows = odin_vizit(BASE, path, args.user, args.password, args.repeats)
    total = statistics.median(r[0] for r in rows)
    db_ms = statistics.median(r[1] for r in rows)
    queries = statistics.median(r[2] for r in rows)
    print("%-38s %10s %10s %8s" % ("операция", "всего, мс", "база, мс", "запросов"))
    print("%-38s %10.1f %10.1f %8.0f" % (path, total, db_ms, queries))
    print("JSON " + json.dumps({
        "url": path, "total_ms": round(total, 1),
        "db_ms": round(db_ms, 1), "queries": int(queries)}))


def normalize(url):
    if url.startswith("http"):
        return url
    url = url if url.startswith("/") else "/" + url
    return quote(url, safe="/?=&%:")


if __name__ == "__main__":
    main()
