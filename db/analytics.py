from datetime import datetime, timedelta

from sqlalchemy import func
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
                    func.cast(PageView.timestamp >= cutoff, type_=func.count().type)
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
