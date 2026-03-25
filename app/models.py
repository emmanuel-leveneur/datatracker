import enum
from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AlertScope(str, enum.Enum):
    PRIVATE = "private"
    GLOBAL = "global"


class ColumnType(str, enum.Enum):
    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    DATE = "date"
    BOOLEAN = "boolean"
    EMAIL = "email"
    SELECT = "select"


class PermissionLevel(str, enum.Enum):
    READ = "read"
    WRITE = "write"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tables: Mapped[list["DataTable"]] = relationship(back_populates="owner")
    owned_tables: Mapped[list["TableOwner"]] = relationship(back_populates="user")
    table_permissions: Mapped[list["TablePermission"]] = relationship(back_populates="user")
    column_permissions: Mapped[list["ColumnPermission"]] = relationship(back_populates="user")
    rows: Mapped[list["TableRow"]] = relationship(back_populates="created_by")


class DataTable(Base):
    __tablename__ = "data_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    owner: Mapped["User"] = relationship(back_populates="tables")
    columns: Mapped[list["TableColumn"]] = relationship(
        back_populates="table", cascade="all, delete-orphan", order_by="TableColumn.order"
    )
    rows: Mapped[list["TableRow"]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )
    permissions: Mapped[list["TablePermission"]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )
    co_owners: Mapped[list["TableOwner"]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )


class TableColumn(Base):
    __tablename__ = "table_columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("data_tables.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    col_type: Mapped[ColumnType] = mapped_column(Enum(ColumnType), default=ColumnType.TEXT)
    order: Mapped[int] = mapped_column(Integer, default=0)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    select_options: Mapped[str] = mapped_column(Text, default="")  # comma-separated

    table: Mapped["DataTable"] = relationship(back_populates="columns")
    cell_values: Mapped[list["CellValue"]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )
    column_permissions: Mapped[list["ColumnPermission"]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )


class TableRow(Base):
    __tablename__ = "table_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("data_tables.id"), nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    table: Mapped["DataTable"] = relationship(back_populates="rows")
    created_by: Mapped["User"] = relationship(back_populates="rows")
    cell_values: Mapped[list["CellValue"]] = relationship(
        back_populates="row", cascade="all, delete-orphan"
    )


class CellValue(Base):
    __tablename__ = "cell_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_id: Mapped[int] = mapped_column(ForeignKey("table_rows.id"), nullable=False)
    column_id: Mapped[int] = mapped_column(ForeignKey("table_columns.id"), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")

    row: Mapped["TableRow"] = relationship(back_populates="cell_values")
    column: Mapped["TableColumn"] = relationship(back_populates="cell_values")


class TablePermission(Base):
    __tablename__ = "table_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("data_tables.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    level: Mapped[PermissionLevel] = mapped_column(
        Enum(PermissionLevel), default=PermissionLevel.READ
    )

    table: Mapped["DataTable"] = relationship(back_populates="permissions")
    user: Mapped["User"] = relationship(back_populates="table_permissions")


class ColumnPermission(Base):
    __tablename__ = "column_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    column_id: Mapped[int] = mapped_column(ForeignKey("table_columns.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    readonly: Mapped[bool] = mapped_column(Boolean, default=False)

    column: Mapped["TableColumn"] = relationship(back_populates="column_permissions")
    user: Mapped["User"] = relationship(back_populates="column_permissions")


class TableOwner(Base):
    __tablename__ = "table_owners"
    __table_args__ = (UniqueConstraint("table_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("data_tables.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    table: Mapped["DataTable"] = relationship(back_populates="co_owners")
    user: Mapped["User"] = relationship(back_populates="owned_tables")


class TableFavorite(Base):
    __tablename__ = "table_favorites"
    __table_args__ = (UniqueConstraint("user_id", "table_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    table_id: Mapped[int] = mapped_column(ForeignKey("data_tables.id"), nullable=False)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(Integer, nullable=False)  # pas de FK — survit à suppression table
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[AlertScope] = mapped_column(Enum(AlertScope), default=AlertScope.PRIVATE)
    conditions: Mapped[str] = mapped_column(Text, default="[]")   # JSON
    actions: Mapped[str] = mapped_column(Text, default="{}")      # JSON
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_by: Mapped["User"] = relationship()
    states: Mapped[list["AlertState"]] = relationship(back_populates="alert", cascade="all, delete-orphan")


class AlertState(Base):
    __tablename__ = "alert_states"
    __table_args__ = (UniqueConstraint("alert_id", "row_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), nullable=False)
    row_id: Mapped[int] = mapped_column(Integer, nullable=False)  # pas de FK — survit à suppression ligne
    is_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    alert: Mapped["Alert"] = relationship(back_populates="states")


class AlertNotification(Base):
    __tablename__ = "alert_notifications"
    __table_args__ = (
        Index("ix_alert_notifications_user_id", "user_id"),
        Index("ix_alert_notifications_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    alert_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # pas de FK — survit à suppression alerte
    alert_name: Mapped[str] = mapped_column(String(128), default="")       # dénormalisé
    row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)     # pas de FK
    table_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # pas de FK
    table_name: Mapped[str] = mapped_column(String(128), default="")       # dénormalisé
    message: Mapped[str] = mapped_column(Text, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship()


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_logs_timestamp", "timestamp"),
        Index("ix_activity_logs_resource_type", "resource_type"),
        # Pas de FK sur table_id : l'historique survit à la suppression de la table
        Index("ix_activity_logs_table_id", "table_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # username est dénormalisé : reste lisible même si l'utilisateur est supprimé
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_name: Mapped[str] = mapped_column(String(256), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    # table_id sans FK — permet de filtrer par table sans cascade sur suppression
    table_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
