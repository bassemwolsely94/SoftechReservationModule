"""
Show every registered OCR engine and whether it's usable right now — the doctor
for the pluggable engine registry (apps.invoices.engines).

Use it to confirm the FREE engines are installed and running, see which paid APIs
are keyed, and learn the exact --engine names the benchmark accepts.

  python manage.py ocr_engines
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "List registered OCR engines and their availability."

    def handle(self, *args, **o):
        from apps.invoices import engines

        specs = engines.all_engine_specs()
        self.stdout.write(self.style.MIGRATE_HEADING(
            "registered OCR engines (free first, then paid APIs):\n"))
        self.stdout.write(f"  {'engine':<12} {'kind':<5} {'available':<10} note")
        self.stdout.write(f"  {'-'*12} {'-'*5} {'-'*10} {'-'*45}")
        for s in specs:
            ok = s.available()
            avail = 'yes' if ok else 'no'
            line = f"  {s.name:<12} {s.kind:<5} {avail:<10} {s.note}"
            self.stdout.write(self.style.SUCCESS(line) if ok else line)

        free = engines.best_free_engine()
        apis = [s.name for s in engines.available_api_specs()]
        self.stdout.write("")
        self.stdout.write(f"  best free engine (auto picks first): {free or '— none installed —'}")
        self.stdout.write(f"  available API engines (escalation order): "
                          f"{', '.join(apis) if apis else '— none keyed —'}")
        self.stdout.write(f"  auto resolves to: {engines.resolve_engine('auto')}")
        self.stdout.write("\n  benchmark A/B: add  --engine <name>  (e.g. --engine paddleocr, "
                          "--engine mistral) to benchmark_vs_softech.")
