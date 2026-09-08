from sqlalchemy import Enum

from app.database.models import (
    AdvertisingStatus,
    CampaignStatus,
    PaymentPlan,
    PaymentStatus,
    ReelJobStatus,
    enum_values,
)


def test_python_enums_persist_lowercase_database_values() -> None:
    assert enum_values(ReelJobStatus) == ["pending", "processing", "completed", "failed"]
    assert enum_values(PaymentStatus) == ["pending", "approved", "rejected"]
    assert enum_values(PaymentPlan) == ["weekly", "monthly"]
    assert enum_values(CampaignStatus) == ["pending", "active", "completed", "cancelled"]
    assert enum_values(AdvertisingStatus) == [
        "pending", "in_review", "approved", "rejected", "completed", "cancelled"
    ]

    column_type = Enum(ReelJobStatus, values_callable=enum_values)
    assert column_type.enums == ["pending", "processing", "completed", "failed"]