"""Simulation ORM models (four-table M1 schema)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class SimulationRun(Base):
    __tablename__ = "simulation_run"

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    scenario: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'town'"))
    seed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'created'")
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    current_tick: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )


class SimTick(Base):
    __tablename__ = "sim_tick"
    # Match f9a1b2c3d4e5 composite unique — keep production index; do not drop.
    __table_args__ = (Index("ix_sim_tick_run_tick", "run_id", "tick_number", unique=True),)

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    tick_number: Mapped[int] = mapped_column(Integer, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class SimAgent(Base):
    __tablename__ = "sim_agent"
    __table_args__ = (Index("ix_sim_agent_run_agent", "run_id", "agent_id", unique=True),)

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(200), nullable=False, server_default=text("''"))
    persona: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    location: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''"))
    position: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    mood: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    activity: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''"))
    goal: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    state_extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )


class SimEvent(Base):
    __tablename__ = "sim_event"
    __table_args__ = (Index("ix_sim_event_run_tick", "run_id", "tick_number"),)

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    tick_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
