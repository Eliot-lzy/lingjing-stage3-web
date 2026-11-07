from __future__ import annotations

from pathlib import Path

from app.database import SessionLocal
from app.models import Task, utc_now
from app.services.vision import run_comparison


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
RESULT_DIR = PROJECT_ROOT / "data" / "results"


def process_task_job(task_id: str, image_path: str) -> None:
    with SessionLocal() as database:
        task = database.get(Task, task_id)
        if task is None:
            return

        task.status = "processing"
        task.error = None
        task.updated_at = utc_now()
        database.commit()

        try:
            result = run_comparison(
                Path(image_path),
                RESULT_DIR / task_id,
            )
        except Exception as error:
            task.status = "failed"
            task.error = str(error)
            task.updated_at = utc_now()
            database.commit()
            return

        task.status = "completed"
        task.result = result
        task.error = None
        task.updated_at = utc_now()
        database.commit()