from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from prices.pipeline.ingest import ingest_file


class Command(BaseCommand):
    help = "Clean raw CSV files and load them as monthly prices. The layout of each file is detected."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", help="CSV files or folders of CSV files")

    def handle(self, *args, **opts):
        files = []
        for p in map(Path, opts["paths"]):
            files += sorted(p.glob("*.csv")) if p.is_dir() else [p]
        if not files:
            raise CommandError("no CSV files found")
        for f in files:
            try:
                result = ingest_file(f)
            except ValueError as exc:
                raise CommandError(f"{f}: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(result.summary()))
