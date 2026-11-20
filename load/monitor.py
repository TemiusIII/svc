"""Монитор потребления ресурсов во время ступени (ДЗ 2, п. 2.6).

Раз в интервал снимает: загрузку процессора приложения и базы данных,
занятую ими память, число соединений с базой — всех и выполняющих запрос
(pg_stat_activity). Средство — чтение /proc (top/pidstat недоступны
в песочнице без прав root), числа сопоставимы с pidstat: % от одного ядра.
"""
import time


class ResourceMonitor:
    """Снимки по процессу api (pid) и по всем процессам postgres."""

    def __init__(self, api_pid, interval=1.0):
        self.api_pid = api_pid
        self.interval = interval
        self.rows = []
        self._t0 = time.time()

    def _cpu_jiffies(self, pid):
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().split()
            # utime + stime (14, 15), клок = 100 на x86
            return (int(parts[13]) + int(parts[14])) / 100.0
        except (FileNotFoundError, ProcessLookupError, IndexError):
            return None

    def _rss_mb(self, pid):
        try:
            with open(f"/proc/{pid}/statm") as f:
                return int(f.read().split()[1]) * 4096 / 1024 / 1024
        except (FileNotFoundError, ProcessLookupError, IndexError):
            return None

    def _postgres_pids(self):
        """Все процессы PostgreSQL: postmaster и рабочие.

        Рабочие процессы («postgres: ...») видны только по /proc/*/comm,
        cmdline у них пуст — ищем и по comm, и по cmdline.
        """
        import glob
        pids = []
        for path in glob.glob("/proc/[0-9]*/comm"):
            try:
                name = open(path).read().strip()
            except OSError:
                continue
            if name == "postgres" or name.startswith("postgres: ") or \
                    name.startswith("checkpointer") or \
                    name.startswith("background") or \
                    name.startswith("walwriter") or \
                    name.startswith("autovacuum") or \
                    name.startswith("logical"):
                pids.append(int(path.split("/")[2]))
        for path in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                cmd = open(path, "rb").read().decode(errors="ignore")
            except OSError:
                continue
            if "pginstall/bin/postgres" in cmd:
                pid = int(path.split("/")[2])
                if pid not in pids:
                    pids.append(pid)
        return pids

    def snapshot(self):
        now = time.time() - self._t0
        api_cpu = self._cpu_jiffies(self.api_pid)
        api_rss = self._rss_mb(self.api_pid)
        pg_pids = self._postgres_pids()
        pg_cpu = sum(filter(None, (self._cpu_jiffies(p) for p in pg_pids)))
        pg_rss = sum(filter(None, (self._rss_mb(p) for p in pg_pids)))

        # Соединения с базой: все и выполняющие запрос (pg_stat_activity).
        conns_total = conns_active = None
        try:
            import psycopg
            with psycopg.connect(
                    "postgresql://app:changeme@/artem_smirnov"
                    "?host=/home/z/my-project/kwr", autocommit=True) as c:
                r = c.execute("""
                    SELECT count(*) AS total,
                           count(*) FILTER (WHERE state = 'active') AS active
                      FROM pg_stat_activity
                     WHERE datname = 'artem_smirnov'
                """).fetchone()
                conns_total, conns_active = r
        except Exception:
            pass

        row = {
            "t": round(now, 1),
            "api_cpu_s": round(api_cpu or 0, 2),
            "api_rss_mb": round(api_rss or 0, 1),
            "pg_cpu_s": round(pg_cpu, 2),
            "pg_rss_mb": round(pg_rss, 1),
            "pg_conns": conns_total,
            "pg_conns_active": conns_active,
        }
        self.rows.append(row)
        return row

    def deltas(self):
        """Приросты CPU за интервал — в процентах одного ядра."""
        out = []
        for prev, cur in zip(self.rows, self.rows[1:]):
            dt = cur["t"] - prev["t"]
            if dt <= 0:
                continue
            out.append({
                "t": cur["t"],
                "api_cpu_pct": round((cur["api_cpu_s"] - prev["api_cpu_s"]) / dt * 100, 1),
                "pg_cpu_pct": round((cur["pg_cpu_s"] - prev["pg_cpu_s"]) / dt * 100, 1),
                "api_rss_mb": cur["api_rss_mb"],
                "pg_rss_mb": cur["pg_rss_mb"],
                "pg_conns": cur["pg_conns"],
                "pg_conns_active": cur["pg_conns_active"],
            })
        return out
