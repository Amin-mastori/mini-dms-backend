import logging
import signal
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from documents.jobs import dispatch_once

logger = logging.getLogger("dms.dispatcher")


class Command(BaseCommand):
    help = "Publish due outbox jobs and recover expired worker leases."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            close_old_connections()
            try:
                published = dispatch_once()
                if options["once"]:
                    self.stdout.write(f"Published {published} jobs.")
            except Exception:
                logger.exception("dispatcher_iteration_failed")
                if options["once"]:
                    raise
            if options["once"]:
                break
            stop.wait(max(0.1, options["interval"]))
