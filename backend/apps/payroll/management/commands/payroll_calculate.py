from django.core.management.base import BaseCommand, CommandError

from apps.payroll import services
from apps.scheduling.models import PayPeriod
from apps.scheduling.services import parse_any_date


class Command(BaseCommand):
    help = ("Fase 20: calcula (o recalcula) la planilla de un periodo de pago con el Web Timer, los segmentos de WFM, la "
            "adherencia guardada y las AP de pago. Con --approve, además la cierra y genera las boletas.")

    def add_arguments(self, parser):
        parser.add_argument("--cycle", help="Código del ciclo de pago predeterminado (p. ej. SV_QUINCENAL).")
        parser.add_argument("--scheduled", action="store_true",
                            help="Fase 21: corrida diaria automática de pre-cierre de los periodos abiertos cuyo corte termina "
                                 "dentro de los días de anticipación configurados (boletas preliminares).")
        parser.add_argument("--period", help="Código del periodo (p. ej. 2026-11-Q1).")
        parser.add_argument("--date", help="O una fecha AAAA-MM-DD contenida en el periodo.")
        parser.add_argument("--approve", action="store_true", help="Cierra la planilla y genera las boletas en masa.")

    def handle(self, *args, **options):
        if options["scheduled"]:
            from apps.payroll.portal import run_scheduled

            done = run_scheduled()
            for item in done:
                self.stdout.write(f"{item}")
            self.stdout.write(self.style.SUCCESS(f"Corridas preliminares: {len([d for d in done if 'error' not in d])}"))
            return
        if not options["cycle"]:
            raise CommandError("Indique --cycle (o --scheduled).")
        periods = PayPeriod.objects.select_related("cycle").filter(cycle__code=options["cycle"].upper())
        if options["period"]:
            period = periods.filter(code=options["period"]).first()
        elif options["date"]:
            d = parse_any_date(options["date"])
            if d is None:
                raise CommandError("Fecha inválida: use AAAA-MM-DD.")
            period = periods.filter(period_start__lte=d, period_end__gte=d).first()
        else:
            raise CommandError("Indique --period o --date.")
        if period is None:
            raise CommandError("No existe ese periodo de pago en el ciclo.")
        try:
            run = services.calculate(period)
            msg = (f"Planilla {run.payroll.payroll_code}: {run.employees} colaboradores, líquido "
                   f"{services.money(run.payroll.total_net)} {run.payroll.currency_code} ({len(run.warnings)} advertencias).")
            if options["approve"]:
                out = services.approve(run)
                msg += f" Cerrada: {out['payslips']} boletas en {out['batches']} lotes."
        except services.PayrollError as exc:
            raise CommandError(exc.message) from None
        self.stdout.write(self.style.SUCCESS(msg))
