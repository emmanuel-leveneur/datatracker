import enum
from datetime import datetime
from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


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


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_logs_timestamp", "timestamp"),
        Index("ix_activity_logs_resource_type", "resource_type"),
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
