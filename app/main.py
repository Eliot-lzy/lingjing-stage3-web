from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.models import Task, utc_now
from app.services.vision import run_comparison


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Lingjing Stage 3 Vision Comparison",
    version="0.3.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def task_to_dict(task: Task) -> dict[str, object]:
    return {
        "id": task.id,
        "original_name": task.original_name,
        "status": task.status,
        "image_format": task.image_format,
        "width": task.image_width,
        "height": task.image_height,
        "size_bytes": task.size_bytes,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def process_task(task_id: str, image_path: Path) -> None:
    with SessionLocal() as database:
        task = database.get(Task, task_id)
        if task is None:
            return

        task.status = "processing"
        task.updated_at = utc_now()
        database.commit()

        try:
            result_dir = RESULT_DIR / task_id
            result = run_comparison(image_path, result_dir)
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024)},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "lingjing-stage3-web",
        "version": "0.3.0",
    }


@app.post("/api/tasks", status_code=202)
async def create_task(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    database: Session = Depends(get_db),
) -> dict[str, object]:
    original_name = image.filename or "upload"
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="仅支持 JPG、JPEG、PNG 和 WEBP 图片。",
        )

    contents = await image.read(MAX_UPLOAD_BYTES + 1)
    await image.close()

    if not contents:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过 10 MB。")

    try:
        with Image.open(io.BytesIO(contents)) as pil_image:
            pil_image.verify()

        with Image.open(io.BytesIO(contents)) as pil_image:
            width, height = pil_image.size
            image_format = pil_image.format or "UNKNOWN"
    except (UnidentifiedImageError, OSError) as error:
        raise HTTPException(
            status_code=400,
            detail="文件不是有效图片。",
        ) from error

    task_id = str(uuid.uuid4())
    saved_path = UPLOAD_DIR / f"{task_id}{extension}"
    saved_path.write_bytes(contents)

    task = Task(
        id=task_id,
        original_name=original_name,
        stored_path=str(saved_path),
        image_format=image_format,
        image_width=width,
        image_height=height,
        size_bytes=len(contents),
        status="queued",
    )

    database.add(task)
    database.commit()
    database.refresh(task)

    background_tasks.add_task(process_task, task.id, saved_path)
    return task_to_dict(task)


@app.get("/api/tasks/{task_id}")
async def get_task(
    task_id: str,
    database: Session = Depends(get_db),
) -> dict[str, object]:
    task = database.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return task_to_dict(task)


@app.get("/results/{task_id}/{filename}")
async def result_file(
    task_id: str,
    filename: str,
) -> FileResponse:
    if Path(task_id).name != task_id or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="结果文件不存在。")

    result_root = RESULT_DIR.resolve()
    result_path = (RESULT_DIR / task_id / filename).resolve()

    if not result_path.is_relative_to(result_root):
        raise HTTPException(status_code=404, detail="结果文件不存在。")

    if not result_path.is_file():
        raise HTTPException(status_code=404, detail="结果文件不存在。")

    return FileResponse(result_path)