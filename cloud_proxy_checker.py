"""
Cloud Proxy Checker - Headless Infinite Loop
============================================
Generates 10,000 random HTTP proxies per batch,
checks them with 500 threads (12s timeout) against http://httpheader.net/,
sends every HIT (HTTP 200) to a Discord webhook,
then repeats forever.

Designed for Render Web Service deployment.
"""

import random
import threading
import requests
import time
import logging
import sys
import os
from queue import Queue
from datetime import datetime, timezone

# =============================================================================
# CONFIGURATION
# =============================================================================

PROXY_COUNT: int = 10_000          # Proxies generated per batch
THREAD_COUNT: int = 500            # Concurrent checker threads
TIMEOUT: int = 12                  # Request timeout in seconds
CHECK_URL: str = "http://httpheader.net/"
GOOD_CODE: int = 200               # HTTP status that means HIT

# --- Load Discord webhook from external file ---
def _load_webhook() -> str:
    """Read the Discord webhook URL from webhook.txt (one line, trimmed)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    webhook_file = os.path.join(script_dir, "webhook.txt")
    if not os.path.isfile(webhook_file):
        raise FileNotFoundError(
            f"webhook.txt not found at {webhook_file}. "
            "Create it with just the webhook URL on a single line."
        )
    with open(webhook_file, "r", encoding="utf-8") as fh:
        url = fh.read().strip()
    if not url:
        raise ValueError(f"webhook.txt at {webhook_file} is empty.")
    return url

WEBHOOK_URL: str = _load_webhook()
WEBHOOK_COOLDOWN: float = 0.5      # Seconds between Discord sends (rate-limit safety)

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("proxy_checker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("CloudProxyChecker")

# =============================================================================
# PROXY GENERATION
# =============================================================================

def generate_http_proxies(count: int) -> list[str]:
    """Generate *count* random HTTP proxies in ``ip:port`` format."""
    logger.info("Generating %d random HTTP proxies ...", count)
    proxies: list[str] = []
    for _ in range(count):
        ip = ".".join(str(random.randint(0, 255)) for _ in range(4))
        port = random.randint(1024, 65535)
        proxies.append(f"{ip}:{port}")
    logger.info("Generated %d proxies.", len(proxies))
    return proxies

# =============================================================================
# DISCORD WEBHOOK
# =============================================================================

# Simple rate-limit guard
_last_webhook_ts: float = 0.0
_webhook_lock = threading.Lock()

def send_to_discord(proxy_str: str) -> bool:
    """POST a working proxy to the Discord webhook. Returns True on success."""
    global _last_webhook_ts
    with _webhook_lock:
        elapsed = time.monotonic() - _last_webhook_ts
        if elapsed < WEBHOOK_COOLDOWN:
            time.sleep(WEBHOOK_COOLDOWN - elapsed)

        try:
            payload = {
                "content": (
                    "**HTTP HIT** -- `{proxy}`\n"
                    "{ts}".format(
                        proxy=proxy_str,
                        ts=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    )
                )
            }
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
            _last_webhook_ts = time.monotonic()

            if resp.status_code in (200, 204):
                logger.info("[DISCORD] Sent OK -> %s", proxy_str)
                return True
            else:
                logger.warning(
                    "Discord returned %d -- body: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
        except Exception as exc:
            logger.error("Discord send failed: %s", exc)
            return False

# =============================================================================
# PROXY CHECKER
# =============================================================================

def check_single_proxy(proxy_str: str) -> bool:
    """
    Test one HTTP proxy against ``CHECK_URL``.
    Returns True if the response status is ``GOOD_CODE``.
    """
    try:
        formatted = f"http://{proxy_str}"
        proxies = {"http": formatted, "https": formatted}
        resp = requests.get(CHECK_URL, proxies=proxies, timeout=TIMEOUT)
        return resp.status_code == GOOD_CODE
    except Exception:
        return False

def worker_thread(
    q: Queue,
    hits: list[str],
    lock: threading.Lock,
    stats: dict,
) -> None:
    """Worker that pulls proxies from the queue and checks them."""
    while True:
        try:
            proxy = q.get_nowait()
        except Exception:
            break

        if check_single_proxy(proxy):
            with lock:
                hits.append(proxy)
            logger.info("[HIT] -> %s", proxy)
            send_to_discord(proxy)

        with lock:
            stats["checked"] += 1

        q.task_done()

# =============================================================================
# BATCH RUNNER
# =============================================================================

def run_batch() -> int:
    """Execute one full batch: generate -> check -> report. Returns hit count."""
    start_ts = time.monotonic()

    proxies = generate_http_proxies(PROXY_COUNT)

    q: Queue = Queue()
    for p in proxies:
        q.put(p)

    hits: list[str] = []
    lock = threading.Lock()
    stats = {"checked": 0}

    logger.info("Spinning up %d worker threads ...", THREAD_COUNT)
    threads: list[threading.Thread] = []
    for _ in range(THREAD_COUNT):
        t = threading.Thread(target=worker_thread, args=(q, hits, lock, stats))
        t.daemon = True
        t.start()
        threads.append(t)

    # Live progress every 10 seconds
    while stats["checked"] < PROXY_COUNT:
        time.sleep(10)
        with lock:
            pct = (stats["checked"] / PROXY_COUNT) * 100
            logger.info(
                "[PROGRESS] %d / %d  (%.1f%%)  |  Hits so far: %d",
                stats["checked"],
                PROXY_COUNT,
                pct,
                len(hits),
            )

    for t in threads:
        t.join()

    elapsed = time.monotonic() - start_ts
    logger.info(
        "[BATCH DONE] Checked: %d  |  Hits: %d  |  Duration: %.1fs",
        stats["checked"],
        len(hits),
        elapsed,
    )
    return len(hits)

# =============================================================================
# MAIN INFINITE LOOP
# =============================================================================

def main() -> None:
    logger.info("=" * 55)
    logger.info("  CLOUD PROXY CHECKER -- Infinite Loop")
    logger.info("  Target : %s", CHECK_URL)
    logger.info("  Threads: %d  |  Timeout: %ds  |  Batch: %d",
                THREAD_COUNT, TIMEOUT, PROXY_COUNT)
    logger.info("  Webhook: %s...", WEBHOOK_URL[:60])
    logger.info("=" * 55)

    batch_num = 0
    while True:
        batch_num += 1
        logger.info("\n%s", "=" * 55)
        logger.info("  >>> BATCH #%d", batch_num)
        logger.info("%s\n", "=" * 55)

        try:
            hits = run_batch()
            logger.info("Batch #%d complete -- %d hits.  Next batch starting ...",
                        batch_num, hits)
        except KeyboardInterrupt:
            logger.info("Shutdown requested. Exiting.")
            sys.exit(0)
        except Exception as exc:
            logger.exception("Batch #%d crashed: %s. Restarting in 15s ...",
                             batch_num, exc)
            time.sleep(15)

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # If Render sets a PORT env var, also spin up a tiny health-check HTTP server
    port = os.environ.get("PORT")
    if port:
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK - Cloud Proxy Checker is running\n")

            def log_message(self, fmt, *args):
                pass  # suppress access logs

        def _start_health_server():
            srv = HTTPServer(("0.0.0.0", int(port)), HealthHandler)
            logger.info("Health-check HTTP server listening on port %s", port)
            srv.serve_forever()

        threading.Thread(target=_start_health_server, daemon=True).start()

    main()