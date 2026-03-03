import time

from django.core.management.base import BaseCommand

from apps.drift_detection_service.service import DriftDetectionService


class Command(BaseCommand):
    help = 'Run per-user drift detection cycle once or in a loop.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true', help='Run continuously')
        parser.add_argument('--interval', type=int, default=300, help='Loop interval in seconds')
        parser.add_argument('--user-id', type=str, help='Run for a single user_id')

    def handle(self, *args, **options):
        loop = options['loop']
        interval = max(5, int(options['interval']))
        user_id = (options.get('user_id') or '').strip()

        service = DriftDetectionService()
        if not loop:
            if user_id:
                run = service.run_cycle_for_user(user_id=user_id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"drift run completed id={run.id} status={run.status} user_id={user_id}"
                    )
                )
                return

            runs = service.run_sweep()
            self.stdout.write(self.style.SUCCESS(f"drift sweep completed users={len(runs)}"))
            return

        loop_target = f"user_id={user_id}" if user_id else "active users"
        self.stdout.write(self.style.WARNING(f"starting drift loop interval={interval}s target={loop_target}"))
        while True:
            if user_id:
                run = service.run_cycle_for_user(user_id=user_id)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"drift run completed id={run.id} status={run.status} user_id={user_id}"
                    )
                )
            else:
                runs = service.run_sweep()
                self.stdout.write(self.style.SUCCESS(f"drift sweep completed users={len(runs)}"))
            time.sleep(interval)
