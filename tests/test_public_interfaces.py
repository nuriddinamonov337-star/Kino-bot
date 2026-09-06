from app.database.models import ReelsJob, SubscriptionCampaign
from app.handlers.admin import admin_command
from app.handlers.movie import movie_code
from app.services.queue import dequeue_job, enqueue_job


def test_requested_public_interfaces_are_available() -> None:
    assert ReelsJob.__tablename__ == "reel_jobs"
    assert SubscriptionCampaign.__tablename__ == "subscriber_campaigns"
    assert callable(admin_command)
    assert callable(movie_code)
    assert callable(enqueue_job)
    assert callable(dequeue_job)