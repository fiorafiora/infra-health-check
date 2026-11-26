"""SQLite tables. One row per client site; months are separate check snapshots."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now()


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    devices: Mapped[list["Device"]] = relationship(
        back_populates="client", passive_deletes=True
    )
    checks: Mapped[list["Check"]] = relationship(
        back_populates="client", passive_deletes=True
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    device_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    serial_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(100), nullable=True)
    warranty_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    added_on: Mapped[date] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    client: Mapped[Client] = relationship(back_populates="devices")
    months: Mapped[list["DeviceMonth"]] = relationship(
        back_populates="device", passive_deletes=True
    )


class Check(Base):
    __tablename__ = "checks"
    __table_args__ = (
        UniqueConstraint("client_id", "year_month", name="uq_client_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    check_date: Mapped[date] = mapped_column(Date)
    year_month: Mapped[str] = mapped_column(String(7))
    engineer: Mapped[str] = mapped_column(String(100))
    connection_method: Mapped[str] = mapped_column(String(20))
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    client: Mapped[Client] = relationship(back_populates="checks")
    items: Mapped[list["CheckItem"]] = relationship(
        back_populates="check", passive_deletes=True
    )
    device_months: Mapped[list["DeviceMonth"]] = relationship(
        back_populates="check", passive_deletes=True
    )
    issue_months: Mapped[list["IssueMonth"]] = relationship(
        back_populates="check", passive_deletes=True
    )


class DeviceMonth(Base):
    __tablename__ = "device_months"
    __table_args__ = (
        UniqueConstraint("check_id", "device_id", name="uq_check_device"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    last_check_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    exception_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_found_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    check: Mapped[Check] = relationship(back_populates="device_months")
    device: Mapped[Device] = relationship(back_populates="months")


class DeviceCheck(Base):
    """A check this device needs every month, set once on the device."""

    __tablename__ = "device_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    device: Mapped[Device] = relationship()
    results: Mapped[list["DeviceCheckResult"]] = relationship(
        back_populates="device_check", passive_deletes=True
    )


class DeviceCheckResult(Base):
    """This month's result for one device check."""

    __tablename__ = "device_check_results"
    __table_args__ = (
        UniqueConstraint("check_id", "device_check_id", name="uq_check_device_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    device_check_id: Mapped[int] = mapped_column(
        ForeignKey("device_checks.id", ondelete="CASCADE"), index=True
    )
    result: Mapped[str | None] = mapped_column(String(10), nullable=True)
    issue: Mapped[str | None] = mapped_column(Text, nullable=True)

    device_check: Mapped[DeviceCheck] = relationship(back_populates="results")


class CustomCheckItem(Base):
    __tablename__ = "custom_check_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CheckItem(Base):
    __tablename__ = "check_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(300))
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_check_items.id", ondelete="SET NULL"), nullable=True
    )
    result: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_result: Mapped[str | None] = mapped_column(String(10), nullable=True)

    check: Mapped[Check] = relationship(back_populates="items")


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("client_id", "code", name="uq_client_issue_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))
    first_found_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20))
    related_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    months: Mapped[list["IssueMonth"]] = relationship(
        back_populates="issue", passive_deletes=True
    )
    device: Mapped[Device | None] = relationship()


class IssueMonth(Base):
    __tablename__ = "issue_months"
    __table_args__ = (
        UniqueConstraint("issue_id", "check_id", name="uq_issue_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[int] = mapped_column(
        ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(10))
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)

    issue: Mapped[Issue] = relationship(back_populates="months")
    check: Mapped[Check] = relationship(back_populates="issue_months")


class Expiry(Base):
    __tablename__ = "expiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(300))
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    related_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    expiry_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    copied_from_device: Mapped[bool] = mapped_column(Boolean, default=False)

    device: Mapped[Device | None] = relationship()


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    stored_name: Mapped[str] = mapped_column(String(80))
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
