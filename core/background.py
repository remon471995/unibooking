"""Runs the daily work by itself, so no cron job is needed on the server.

A small thread starts with the web server (gunicorn / runserver) and, about once a day, creates the installment
notifications (core/daily.py).  Every notification is created only once, so several workers or a restart never
send duplicates.  It does NOT start for tests, migrations, collectstatic or any other management command.
Set DISABLE_BACKGROUND_JOBS=1 to turn it off (for example when a real scheduler runs `manage.py installment_reminders`).
"""
import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)
_started = False


def _is_web_server():
    argv = sys.argv
    exe = os.path.basename(argv[0]).lower() if argv else ""
    if "gunicorn" in exe or "uvicorn" in exe or "daphne" in exe:
        return True
    if len(argv) > 1 and argv[1] == "runserver":
        return os.environ.get("RUN_MAIN") == "true" or "--noreload" in argv     # not the autoreloader's parent
    return False


def _loop(first_delay, every):
    from django.db import close_old_connections
    from django.utils import timezone

    from .daily import send_installment_notifications

    time.sleep(first_delay)                      # let the app finish starting
    last_day = None
    while True:
        try:
            today = timezone.localdate()
            if today != last_day:
                created = send_installment_notifications(today)
                last_day = today
                log.info("daily installment notifications created: %s", created)
        except Exception:                        # never let the thread die
            log.exception("daily installment notifications failed")
        finally:
            close_old_connections()
        time.sleep(every)


def start(first_delay=90, every=3600):
    global _started
    if _started or os.environ.get("DISABLE_BACKGROUND_JOBS") or not _is_web_server():
        return False
    _started = True
    threading.Thread(target=_loop, args=(first_delay, every), name="daily-jobs", daemon=True).start()
    return True
