import time

from django.core.management.base import BaseCommand

from apps.embedding_service.service import EmbeddingService


class Command(BaseCommand):
    help = 'Process pending embedding sync jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true', help='Run continuously')
        parser.add_argument('--interval', type=int, default=30, help='Loop interval in seconds')
        parser.add_argument('--limit', type=int, default=50, help='Max jobs per cycle')

    def handle(self, *args, **options):
        loop = options['loop']
        interval = max(2, int(options['interval']))
        limit = max(1, int(options['limit']))

        service = EmbeddingService()
        if not loop:
            processed = service.process_pending_jobs(limit=limit)
            self.stdout.write(self.style.SUCCESS(f'processed={processed}'))
            return

        self.stdout.write(self.style.WARNING(f'starting embedding loop interval={interval}s limit={limit}'))
        while True:
            processed = service.process_pending_jobs(limit=limit)
            self.stdout.write(self.style.SUCCESS(f'processed={processed}'))
            time.sleep(interval)
