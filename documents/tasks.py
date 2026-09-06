from celery import shared_task

from documents.jobs import run_job


@shared_task(
    name="documents.execute_job", acks_late=True, reject_on_worker_lost=True, ignore_result=True
)
def execute_job(job_id):
    """Retries are persisted in PostgreSQL, not scheduled in two separate systems."""
    return run_job(job_id)
