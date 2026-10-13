from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Line(Base):
    __tablename__ = "lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    takt_time_sec: Mapped[float] = mapped_column(Float, default=60.0)
    shift_start: Mapped[str] = mapped_column(String(5), default="08:00")
    shift_end: Mapped[str] = mapped_column(String(5), default="20:00")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Station(Base):
    """One process step of a line."""

    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), default="")
    operation: Mapped[str] = mapped_column(Text, default="")
    parts_added: Mapped[list] = mapped_column(JSON, default=list)
    target_cycle_sec: Mapped[float] = mapped_column(Float, default=60.0)
    expected_picks: Mapped[int] = mapped_column(Integer, default=2)
    operator_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id", ondelete="CASCADE"), index=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(20), default="rtsp")
    source: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    zones: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"))
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id", ondelete="CASCADE"))
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime] = mapped_column(DateTime)
    cycle_sec: Mapped[float] = mapped_column(Float)
    work_sec: Mapped[float] = mapped_column(Float, default=0.0)
    motion_waste_sec: Mapped[float] = mapped_column(Float, default=0.0)
    wait_sec: Mapped[float] = mapped_column(Float, default=0.0)
    hand_travel_m: Mapped[float] = mapped_column(Float, default=0.0)
    reach_count: Mapped[int] = mapped_column(Integer, default=0)
    walk_m: Mapped[float] = mapped_column(Float, default=0.0)
    pick_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="vision")
    over_target: Mapped[bool] = mapped_column(Boolean, default=False)
    # {"hand": [[x,y],...], "body": [[x,y],...]} normalized; only kept for vision/simulated cycles
    track: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    __table_args__ = (
        Index("ix_cycles_station_ended", "station_id", "ended_at"),
        Index("ix_cycles_line_ended", "line_id", "ended_at"),
        Index("ix_cycles_camera_ended", "camera_id", "ended_at"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class HeatmapDay(Base):
    """Accumulated hand-position heatmap per camera per day (row-major grid of counts)."""

    __tablename__ = "heatmaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    cols: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    grid: Mapped[list] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("camera_id", "day", name="uq_heatmap_camera_day"),)


class ElementModel(Base):
    """Learned work elements of one camera (spots, standard sequence & times, user names)."""

    __tablename__ = "element_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    model: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AnalysisCycle(Base):
    """One operator cycle broken into elements and compared with the standard."""

    __tablename__ = "analysis_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(Integer, index=True)
    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[int] = mapped_column(Integer)
    start_ts: Mapped[float] = mapped_column(Float, index=True)  # unix time (matches the recordings)
    end_ts: Mapped[float] = mapped_column(Float)
    cycle_sec: Mapped[float] = mapped_column(Float)
    elements: Mapped[list] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="ok")
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
