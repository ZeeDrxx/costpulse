from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand

from prices.models import Observation


class Command(BaseCommand):
    help = "First-run demo: if the database is empty, generate sample data, ingest it and train forecasts."

    def add_arguments(self, parser):
        parser.add_argument("--raw", default="data/raw")

    def handle(self, *args, **opts):
        if Observation.objects.exists():
            self.stdout.write("Database already has prices; nothing to do.")
            return
        raw = Path(opts["raw"])
        if not any(raw.glob("*.csv")):
            call_command("generate_sample", out=str(raw))
        call_command("ingest", str(raw))
        call_command("train_forecasts")
