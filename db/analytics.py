from datetime import datetime, timedelta

from sqlalchemy import case, func
from db.models import PageView
from db.session import get_session


def log_page_view(path: str) -> None:
    """Insert an anonymous page view record."""
    with get_session() as session:
        session.add(PageView(path=path))


def get_page_views(days: int = 30) -> list[dict]:
    """Page views grouped by path + day for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(
                PageView.path,
                func.date(PageView.timestamp).label("date"),
                func.count().label("views"),
            )
            .filter(PageView.timestamp >= cutoff)
            .group_by(PageView.path, func.date(PageView.timestamp))
            .order_by(func.date(PageView.timestamp))
            .all()
        )
        return [{"path": r.path, "date": str(r.date), "views": r.views} for r in rows]


def get_page_views_summary() -> list[dict]:
    """Total views per page: all time and last 30 days."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    with get_session() as session:
        rows = (
            session.query(
                PageView.path,
                func.count().label("total_views"),
                func.sum(
                    case((PageView.timestamp >= cutoff, 1), else_=0)
                ).label("views_30d"),
            )
            .group_by(PageView.path)
            .order_by(func.count().desc())
            .all()
        )
        return [
            {"path": r.path, "total_views": r.total_views, "views_30d": int(r.views_30d or 0)}
            for r in rows
        ]


def get_views_per_day(days: int = 30) -> list[dict]:
    """Total views per day for the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(
                func.date(PageView.timestamp).label("date"),
                func.count().label("views"),
            )
            .filter(PageView.timestamp >= cutoff)
            .group_by(func.date(PageView.timestamp))
            .order_by(func.date(PageView.timestamp))
            .all()
        )
        return [{"date": str(r.date), "views": r.views} for r in rows]


def get_recent_views(limit: int = 50) -> list[dict]:
    """Most recent page views."""
    with get_session() as session:
        rows = (
            session.query(PageView.path, PageView.timestamp)
            .order_by(PageView.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [{"path": r.path, "timestamp": str(r.timestamp)} for r in rows]


def get_hourly_heatmap(days: int = 30) -> list[dict]:
    """Views grouped by day-of-week and hour-of-day for a heatmap."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(
                func.extract("dow", PageView.timestamp).label("dow"),
                func.extract("hour", PageView.timestamp).label("hour"),
                func.count().label("views"),
            )
            .filter(PageView.timestamp >= cutoff)
            .group_by("dow", "hour")
            .all()
        )
        return [
            {"dow": int(r.dow), "hour": int(r.hour), "views": r.views}
            for r in rows
        ]


def get_hourly_distribution(days: int = 30) -> list[dict]:
    """Total views per hour-of-day."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with get_session() as session:
        rows = (
            session.query(
                func.extract("hour", PageView.timestamp).label("hour"),
                func.count().label("views"),
            )
            .filter(PageView.timestamp >= cutoff)
            .group_by("hour")
            .order_by("hour")
            .all()
        )
        return [{"hour": int(r.hour), "views": r.views} for r in rows]


def get_week_over_week() -> dict:
    """Compare this week's views vs last week's."""
    now = datetime.utcnow()
    this_week_start = now - timedelta(days=now.weekday())
    this_week_start = this_week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    last_week_start = this_week_start - timedelta(days=7)

    with get_session() as session:
        this_week = (
            session.query(func.count(PageView.id))
            .filter(PageView.timestamp >= this_week_start)
            .scalar()
            or 0
        )
        last_week = (
            session.query(func.count(PageView.id))
            .filter(
                PageView.timestamp >= last_week_start,
                PageView.timestamp < this_week_start,
            )
            .scalar()
            or 0
        )

        if last_week > 0:
            change_pct = round(((this_week - last_week) / last_week) * 100, 1)
        else:
            change_pct = None

        return {
            "this_week": this_week,
            "last_week": last_week,
            "change_pct": change_pct,
        }


def get_total_stats() -> dict:
    """Aggregate stats for summary cards."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    with get_session() as session:
        total_views = session.query(func.count(PageView.id)).scalar() or 0
        views_30d = (
            session.query(func.count(PageView.id))
            .filter(PageView.timestamp >= cutoff)
            .scalar()
            or 0
        )

        top_page_row = (
            session.query(PageView.path, func.count().label("cnt"))
            .filter(PageView.timestamp >= cutoff)
            .group_by(PageView.path)
            .order_by(func.count().desc())
            .first()
        )

        return {
            "total_views": total_views,
            "views_30d": views_30d,
            "top_page": {"path": top_page_row.path, "cnt": top_page_row.cnt}
            if top_page_row
            else {"path": "N/A", "cnt": 0},
        }
