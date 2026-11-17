from django.core.management.base import BaseCommand

from prices.sample import generate


class Command(BaseCommand):
    help = "Write synthetic raw CSVs (fuel notices, market survey, rent listings) for demos and tests."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="data/raw")
        parser.add_argument("--start", default="2021-01")
        parser.add_argument("--end", default="2026-10")
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, **opts):
        for source, path in generate(opts["out"], opts["start"], opts["end"], opts["seed"]).items():
            self.stdout.write(f"{source:<7} {path}")
