from sqlalchemy import Enum

from app.database.models import (
    AdContentType,
    AdStatus,
    AdTariff,
    PaymentPlan,
    PaymentStatus,
    ReelJobStatus,
    enum_values,
)


def test_python_enums_persist_lowercase_database_values() -> None:
    assert enum_values(ReelJobStatus) == ["pending", "processing", "completed", "failed"]
    assert enum_values(PaymentStatus) == ["pending", "approved", "rejected"]
    assert enum_values(PaymentPlan) == ["weekly", "monthly"]
    assert enum_values(AdTariff) == ["week", "month"]

    assert enum_values(AdStatus) == ["pending", "approved", "rejected", "active", "completed"]
    assert enum_values(AdContentType) == ["video", "photo", "document"]

    column_type = Enum(ReelJobStatus, values_callable=enum_values)
    assert column_type.enums == ["pending", "processing", "completed", "failed"]