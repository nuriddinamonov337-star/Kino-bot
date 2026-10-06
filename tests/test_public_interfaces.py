from app.database.models import AdCampaign, ReelJob
from app.handlers.admin_panel import admin_command
from app.handlers.movies import movie_code
from app.services.queue import dequeue_job, enqueue_job


def test_requested_public_interfaces_are_available() -> None:
    assert ReelJob.__tablename__ == "reel_jobs"
    assert AdCampaign.__tablename__ == "ad_campaigns"

    assert callable(admin_command)
    assert callable(movie_code)
    assert callable(enqueue_job)
    assert callable(dequeue_job)
