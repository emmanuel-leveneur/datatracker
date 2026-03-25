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


def reevaluate_temporal_alerts():
    """
    Réévalue toutes les alertes actives contenant un opérateur temporel relatif
    (before_today, after_today, today_or_before, today_or_after, today, yesterday, tomorrow).
    Appelé chaque matin pour que les alertes date restent à jour sans modification de ligne.
    """
    from app.database import SessionLocal
    from app.models import Alert, DataTable, TableRow
    from app.alerts import evaluate_alerts_for_row

    TEMPORAL_OPS = {
        "before_today", "after_today", "today_or_before", "today_or_after",
        "today", "yesterday", "tomorrow",
    }

    db = SessionLocal()
    try:
        import json
        active_alerts = db.query(Alert).filter_by(is_active=True).all()
        # Garde uniquement les alertes qui ont au moins un opérateur temporel
        table_ids: set[int] = set()
        for alert in active_alerts:
            try:
                conditions = json.loads(alert.conditions or "[]")
            except Exception:
                continue
            if any(c.get("operator") in TEMPORAL_OPS for c in conditions):
                table_ids.add(alert.table_id)

        total_rows = 0
        for table_id in table_ids:
            table = db.get(DataTable, table_id)
            if not table:
                continue
            rows = db.query(TableRow).filter(
                TableRow.table_id == table_id,
                TableRow.deleted_at == None,
            ).all()
            for row in rows:
                evaluate_alerts_for_row(db, row, table)
            if rows:
                db.commit()
            total_rows += len(rows)

        logger.info(f"[scheduler] reevaluate_temporal_alerts: {len(table_ids)} table(s), {total_rows} ligne(s)")
    except Exception as e:
        logger.error(f"[scheduler] reevaluate_temporal_alerts error: {e}")
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(
        cleanup_orphan_rows,
        CronTrigger(hour=3, minute=0),
        id="cleanup_orphan_rows",
        replace_existing=True,
    )
    scheduler.add_job(
        reevaluate_temporal_alerts,
        CronTrigger(hour=6, minute=0),  # Chaque jour à 6h00
        id="reevaluate_temporal_alerts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[scheduler] APScheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] APScheduler stopped")
