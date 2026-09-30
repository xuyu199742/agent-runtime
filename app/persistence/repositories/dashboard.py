from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.persistence.database import ExecutionSpec, Run


class DashboardRepository:
    def __init__(self, db):
        self.db = db

    async def summary(self) -> dict:
        now = datetime.now(UTC)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=6)
        statuses = (
            await self.db.execute(
                select(Run.status, func.count(Run.id))
                .where(Run.created_at >= today)
                .group_by(Run.status)
            )
        ).all()
        counts = {status: count for status, count in statuses}
        total = sum(counts.values())
        active_rows = (
            await self.db.execute(
                select(Run.status, func.count(Run.id))
                .where(Run.status.in_(["RUNNING", "WAITING"]))
                .group_by(Run.status)
            )
        ).all()
        active_counts = {status: count for status, count in active_rows}
        duration_ms = await self.db.scalar(
            select(func.avg(func.extract("epoch", Run.completed_at - Run.started_at) * 1000)).where(
                Run.created_at >= today, Run.started_at.is_not(None), Run.completed_at.is_not(None)
            )
        )
        trend_rows = (
            await self.db.execute(
                select(
                    func.date_trunc("day", Run.created_at).label("day"),
                    Run.status,
                    func.count(Run.id),
                )
                .where(Run.created_at >= week)
                .group_by("day", Run.status)
                .order_by("day", Run.status)
            )
        ).all()
        error_rows = (
            await self.db.execute(
                select(Run.error_code, func.count(Run.id))
                .where(Run.created_at >= week, Run.error_code.is_not(None))
                .group_by(Run.error_code)
                .order_by(func.count(Run.id).desc())
                .limit(10)
            )
        ).all()
        model_name = ExecutionSpec.snapshot["model"]["model_name"].as_string()
        model_rows = (
            await self.db.execute(
                select(model_name, func.count(Run.id))
                .join(ExecutionSpec, ExecutionSpec.id == Run.execution_spec_id)
                .where(Run.created_at >= week)
                .group_by(model_name)
                .order_by(func.count(Run.id).desc())
                .limit(10)
            )
        ).all()
        failed = (
            await self.db.execute(
                select(Run.id, Run.error_code, Run.created_at)
                .where(Run.status == "FAILED")
                .order_by(Run.created_at.desc())
                .limit(10)
            )
        ).all()
        waiting = (
            await self.db.execute(
                select(Run.id, Run.waiting_at)
                .where(Run.status == "WAITING")
                .order_by(Run.waiting_at)
                .limit(10)
            )
        ).all()
        oldest_pending = await self.db.scalar(
            select(func.min(Run.created_at)).where(Run.status == "PENDING")
        )
        completed = counts.get("COMPLETED", 0)
        failed_count = counts.get("FAILED", 0)
        settled = completed + failed_count
        return {
            "today_runs": total,
            "running": active_counts.get("RUNNING", 0),
            "waiting": active_counts.get("WAITING", 0),
            "failed": failed_count,
            "average_duration_ms": round(float(duration_ms), 1)
            if duration_ms is not None
            else None,
            "success_rate": round(completed / settled, 4) if settled else None,
            "run_trend": [
                {"day": day.date().isoformat(), "status": status, "count": count}
                for day, status, count in trend_rows
            ],
            "error_trend": [{"code": code, "count": count} for code, count in error_rows],
            "model_usage": [{"model": name, "count": count} for name, count in model_rows],
            "recent_failed": [
                {"id": run_id, "error_code": code, "created_at": created}
                for run_id, code, created in failed
            ],
            "waiting_approvals": [{"run_id": run_id, "waiting_at": at} for run_id, at in waiting],
            "oldest_pending_at": oldest_pending,
        }
