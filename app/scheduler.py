from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def cleanup_orphan_rows():
    """Remove rows that have no cell values (cleanup task example)."""
    from app.database import SessionLocal
    from app.models import TableRow, CellValue
    from sqlalchemy import select, not_, exists

    db = SessionLocal()
    try:
        orphans = db.execute(
            select(TableRow).where(
                TableRow.deleted_at == None,
                not_(
                    exists().where(CellValue.row_id == TableRow.id)
                )
            )
        ).scalars().all()
        for row in orphans:
            db.delete(row)
        db.commit()
        if orphans:
            logger.info(f"[scheduler] Cleaned up {len(orphans)} orphan rows at {datetime.now()}")
    except Exception as e:
        logger.error(f"[scheduler] cleanup_orphan_rows error: {e}")
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(
        cleanup_orphan_rows,
        CronTrigger(hour=3, minute=0),  # Every day at 3:00 AM
        id="cleanup_orphan_rows",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[scheduler] APScheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] APScheduler stopped")
