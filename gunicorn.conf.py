# Gunicorn configuration for NetKPI Monitor (Linux production)
# Usage: gunicorn -c gunicorn.conf.py "app:create_app()"

import multiprocessing
import os

# ── Server Socket ────────────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5001")

# ── Worker Processes ─────────────────────────────────────────────────────────
# For ~10 concurrent users with DB-heavy workload, 2-4 workers is optimal
workers = int(os.getenv("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 4)))
worker_class = "gthread"  # threaded workers for I/O-bound DB queries
threads = int(os.getenv("GUNICORN_THREADS", 4))

# ── Timeouts ─────────────────────────────────────────────────────────────────
timeout = 120          # Kill workers stuck for >2 min (heavy KPI queries)
graceful_timeout = 30  # Allow 30s for in-progress requests to finish on restart
keepalive = 5          # Keep connections alive for 5s

# ── Logging ──────────────────────────────────────────────────────────────────
accesslog = "-"         # stdout
errorlog = "-"          # stderr
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# ── Security ─────────────────────────────────────────────────────────────────
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# ── Process Naming ───────────────────────────────────────────────────────────
proc_name = "netkpi-monitor"

# ── Preload ──────────────────────────────────────────────────────────────────
preload_app = True  # Load app before forking workers (saves memory, faster startup)
