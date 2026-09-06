import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from documents.models import Job


class Command(BaseCommand):
    help = "Explicitly rearm one failed object-cleanup job after fixing its cause."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=uuid.UUID)

    @transaction.atomic
    def handle(self, *args, **options):
        job = (
            Job.objects.select_for_update()
            .filter(pk=options["job_id"], kind=Job.Kind.DELETE, state=Job.State.FAILED)
            .first()
        )
        if not job:
            raise CommandError("No failed cleanup job exists with that ID.")
        job.state = Job.State.PENDING
        job.attempts = 0
        job.error_code = ""
        job.dispatched_at = None
        job.available_at = timezone.now()
        job.save()
        self.stdout.write(self.style.SUCCESS(f"Cleanup job {job.id} rearmed."))
