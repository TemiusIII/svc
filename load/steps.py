"""Оркестратор ступенчатого испытания (ДЗ 2, пп. 2.4–2.6).

Для каждой ступени: наполняет базу заново, ждёт возврата загрузки
процессора к простою, запускает k6 (ступень на DURATION секунд),
параллельно пишет ряд потребления ресурсов, парсит итог k6.
Порог методички: p95 < 500 мс, доля ошибок < 1 %.

    python load/steps.py mixed 1 2 4 8 16     # ступени от 1 rps
    python load/steps.py heavy 1 2 4          # тяжёлая операция

Результат — JSON в scripts/hw2_steps_<scenario>.json.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from monitor import ResourceMonitor  # noqa: E402

SVC = Path("/home/z/my-project/svc")
DURATION = "30s"
RESULTS = Path("/home/z/my-project/scripts")

ENV = {
    "PATH": "/home/z/.venv/bin:/usr/bin:/bin",
    "SEED_DSN": "postgresql://app:changeme@/artem_smirnov?host=/home/z/my-project/kwr",
    "DATABASE_URL": "postgresql+asyncpg://app:changeme@/artem_smirnov?host=/home/z/my-project/kwr",
    "DB_SCHEMA": "artem_smirnov",
    "APP_POOL_SIZE": "10",  # default; меняется опытом с настройкой
}


def seed(volume="full"):
    out = subprocess.run(["python3", "db/seed.py", volume], env=ENV,
                         cwd=SVC, capture_output=True, text=True, timeout=600)
    if "готово" not in out.stdout:
        raise RuntimeError(out.stderr[-500:])


def api_pid():
    """PID процесса api/run.py (не pgrep -f: он матчит и сам bash-скрипт).

    Запуск из api/ командой python3 run.py: cmdline = ["python3", "run.py"].
    """
    import glob
    for path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            cmd = open(path, "rb").read().decode(errors="ignore")
        except OSError:
            continue
        argv = [a for a in cmd.split("\x00") if a]
        if len(argv) == 2 and argv[0].endswith("python3") and \
                argv[1] == "run.py":
            return int(path.split("/")[2])
        if len(argv) >= 2 and argv[1].endswith("api/run.py"):
            return int(path.split("/")[2])
    return None


def wait_idle(pid, threshold=5.0, timeout=60):
    """Подождать возврата загрузки процессора к простою."""
    mon = ResourceMonitor(pid)
    last = mon.snapshot()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        cur = mon.snapshot()
        dt = cur["t"] - last["t"]
        if dt > 0:
            cpu_pct = (cur["api_cpu_s"] - last["api_cpu_s"]) / dt * 100
            if cpu_pct < threshold:
                return
        last = cur


def parse_k6(out):
    """Итог k6 из текстового вывода: p95, ошибки, dropped, частота."""
    data = {"p95_ms": None, "err_rate": None, "dropped": 0,
            "actual_rate": None, "max_ms": None, "p50_ms": None}
    for line in out.splitlines():
        m = re.search(r"http_req_duration.*?med=([\d.]+)ms.*?p\(95\)=([\d.]+)ms", line)
        if m and data["p95_ms"] is None:
            data["p50_ms"] = float(m.group(1))
            data["p95_ms"] = float(m.group(2))
        m = re.search(r"http_req_duration.*?max=([\d.]+)ms", line)
        if m and data["max_ms"] is None:
            data["max_ms"] = float(m.group(1))
        m = re.search(r"http_req_failed\.*: ([\d.]+)%", line)
        if m and data["err_rate"] is None:
            data["err_rate"] = float(m.group(1))
        m = re.search(r"dropped_iterations.*", line)
        if m:
            n = re.search(r"(\d+)", line.split(":")[1] if ":" in line else "0")
            data["dropped"] = int(n.group(1)) if n else 0
        m = re.search(r"http_reqs\.*:\s+(\d+)\s+([\d.]+)/s", line)
        if m and data["actual_rate"] is None:
            data["requests"] = int(m.group(1))
            data["actual_rate"] = float(m.group(2))
        m = re.search(r"iterations\.*:\s+(\d+)\s+([\d.]+)/s", line)
        if m and "iterations" not in data:
            data["iterations"] = int(m.group(1))
    # dropped_iterations: count value
    m = re.search(r"dropped_iterations\.*:\s+(\d+)", out)
    if m:
        data["dropped"] = int(m.group(1))
    return data


def run_step(scenario, rate, pid):
    """Одна ступень: k6 в фоне + монитор ресурсов."""
    mon = ResourceMonitor(pid, interval=1.0)
    cmd = ["k6", "run", "load/tests/step.test.js",
           f"-e", f"SCENARIO={scenario}",
           f"-e", f"RATE={rate}",
           f"-e", f"DURATION={DURATION}",
           "--summary-export", f"/tmp/k6_{scenario}_{rate}.json"]
    proc = subprocess.Popen(cmd, env=ENV, cwd=SVC,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    deadline = time.time() + 120
    while proc.poll() is None and time.time() < deadline:
        mon.snapshot()
        time.sleep(1.0)
    out = proc.stdout.read()
    proc.wait()
    # Ещё пара снимков после ступени — спад нагрузки.
    for _ in range(3):
        mon.snapshot()
        time.sleep(1.0)
    stats = parse_k6(out)
    # p95/err/dropped берём из summary-export — надёжнее парсинга текста.
    try:
        summary = json.loads(Path(f"/tmp/k6_{scenario}_{rate}.json").read_text())
        m = summary["metrics"]
        stats["p95_ms"] = round(m["http_req_duration"].get("p(95)", 0), 1)
        stats["p50_ms"] = round(m["http_req_duration"].get("med", 0), 1)
        stats["max_ms"] = round(m["http_req_duration"].get("max", 0), 1)
        stats["err_rate"] = round(m["http_req_failed"].get("value", 0) * 100, 2)
        stats["dropped"] = m.get("dropped_iterations", {}).get("count", 0)
        stats["actual_rate"] = round(m["http_reqs"].get("rate", 0), 2)
    except (OSError, KeyError, ValueError):
        pass
    # Максимальная загрузка за ступень (не первые/последние снятия).
    deltas = mon.deltas()
    core = [d for d in deltas if d["t"] <= 40]  # сама ступень
    if core:
        peak = max(core, key=lambda d: d["api_cpu_pct"])
        stats["resources"] = peak
        stats["resources_rows"] = deltas
    # Сводные по ступени: среднее за ядро ступени.
    if core:
        stats["api_cpu_avg"] = round(sum(d["api_cpu_pct"] for d in core) / len(core), 1)
        stats["pg_cpu_avg"] = round(sum(d["pg_cpu_pct"] for d in core) / len(core), 1)
        stats["conns_max"] = max(d["pg_conns"] or 0 for d in core)
        stats["conns_active_max"] = max(d["pg_conns_active"] or 0 for d in core)
    return stats, out


def warmup(scenario):
    """Прогрев после наполнения: кеш PostgreSQL сбрасывается пересозданием
    таблиц, и первая минута ступени уходит на чтение с диска. Прогрев —
    проходка k6 на 1 rps 6 секунд, в результаты не входит."""
    subprocess.run(
        ["k6", "run", "load/tests/step.test.js",
         "-e", f"SCENARIO={scenario}", "-e", "RATE=1", "-e", "DURATION=6s",
         "--summary-export", "/tmp/k6_warmup.json"],
        env=ENV, cwd=SVC, capture_output=True, text=True, timeout=120)


def main():
    scenario = sys.argv[1]
    rates = [int(x) for x in sys.argv[2:]] or [1, 2, 4, 8, 16]
    pid = api_pid()
    print(f"api pid: {pid}, сценарий {scenario}, ступени {rates}")
    results = []
    for rate in rates:
        seed()                      # перед каждым испытанием база заново
        warmup(scenario)            # кеш после наполнения — тёплый
        wait_idle(pid)
        stats, out = run_step(scenario, rate, pid)
        stats["rate"] = rate
        stats["scenario"] = scenario
        results.append(stats)
        ok = (stats["p95_ms"] or 0) < 500 and (stats["err_rate"] or 0) < 1
        print(f"ступень {rate} rps: p95={stats['p95_ms']} мс, "
              f"err={stats['err_rate']}%, p95 ok={ok}, "
              f"api_cpu~{stats.get('api_cpu_avg')}%, pg_cpu~{stats.get('pg_cpu_avg')}%")
        # Точка излома: порог нарушен — дальше не поднимаемся.
        if not ok:
            print(f"порог нарушен на {rate} rps — стоп")
            break
        time.sleep(5)
    path = RESULTS / f"hw2_steps_{scenario}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("saved", path)


if __name__ == "__main__":
    main()
