from __future__ import annotations

import io
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from rq.job import Job
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import (
    clear_auth_cookie,
    create_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    set_auth_cookie,
    validate_auth_config,
    verify_password,
)
from app.database import Base, engine, ensure_schema, get_db
from app.models import Task, User, utc_now
from app.queue import get_queue
from app.schemas import Credentials, TaskUpdate
from app.tasks import process_task_job


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
    validate_auth_config()
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    yield


app = FastAPI(
    title="Lingjing Stage 3 Vision Comparison",
    version="0.5.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def task_title(task: Task) -> str:
    return task.title or task.original_name


def task_to_dict(task: Task) -> dict[str, object]:
    return {
        "id": task.id,
        "title": task_title(task),
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


def task_to_summary(task: Task) -> dict[str, object]:
    result = task.result or {}
    traditional = result.get("traditional") or {}
    multimodal = result.get("multimodal") or {}

    return {
        "id": task.id,
        "title": task_title(task),
        "original_name": task.original_name,
        "status": task.status,
        "width": task.image_width,
        "height": task.image_height,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "object_count": traditional.get("object_count", 0),
        "item_count": multimodal.get(
            "item_count_sum",
            multimodal.get("total_objects", 0),
        ),
        "error": task.error,
    }


def auth_response(user: User) -> dict[str, object]:
    token = create_access_token(user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
        },
    }


def get_owned_task(
    task_id: str,
    user: User,
    database: Session,
) -> Task:
    task = database.get(Task, task_id)
    if task is None or task.owner_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return task


def delete_safe_file(path: Path, root: Path) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path.is_relative_to(resolved_root) and resolved_path.is_file():
        resolved_path.unlink(missing_ok=True)


@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> HTMLResponse | RedirectResponse:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={},
    )


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> HTMLResponse | RedirectResponse:
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "user_email": user.email,
        },
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> HTMLResponse | RedirectResponse:
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={"user_email": user.email},
    )


@app.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    clear_auth_cookie(response)
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "lingjing-stage3-web",
        "version": "0.5.0",
    }


@app.post("/api/auth/register")
def register(
    payload: Credentials,
    response: Response,
    database: Session = Depends(get_db),
) -> dict[str, object]:
    email = normalize_email(payload.email)
    password = payload.password

    if "@" not in email or len(email) > 255:
        raise HTTPException(status_code=400, detail="邮箱格式不正确。")
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(
            status_code=400,
            detail="密码长度必须在 8 到 128 个字符之间。",
        )

    existing = database.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="该邮箱已经注册。")

    user_count = database.scalar(
        select(func.count()).select_from(User)
    ) or 0

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
    )
    database.add(user)
    database.flush()

    if user_count == 0:
        database.execute(
            update(Task)
            .where(Task.owner_id.is_(None))
            .values(
                owner_id=user.id,
                title=func.coalesce(Task.title, Task.original_name),
            )
        )

    database.commit()
    database.refresh(user)

    result = auth_response(user)
    set_auth_cookie(response, str(result["access_token"]))
    return result


@app.post("/api/auth/login")
def login(
    payload: Credentials,
    response: Response,
    database: Session = Depends(get_db),
) -> dict[str, object]:
    email = normalize_email(payload.email)
    user = database.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="邮箱或密码错误。",
        )

    result = auth_response(user)
    set_auth_cookie(response, str(result["access_token"]))
    return result


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
    }


@app.post("/api/tasks", status_code=202)
async def create_task(
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
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
        owner_id=user.id,
        title=original_name[:255],
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

    try:
        get_queue().enqueue(
            process_task_job,
            task.id,
            str(saved_path),
            job_id=task.id,
            job_timeout=600,
            result_ttl=3600,
            failure_ttl=86400,
        )
    except Exception as error:
        task.status = "failed"
        task.error = f"任务入队失败: {error}"
        task.updated_at = utc_now()
        database.commit()
        raise HTTPException(
            status_code=503,
            detail="任务队列暂不可用。",
        ) from error

    return task_to_dict(task)


@app.get("/api/tasks")
def list_tasks(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> dict[str, object]:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    conditions = Task.owner_id == user.id
    total = database.scalar(
        select(func.count()).select_from(Task).where(conditions)
    ) or 0
    tasks = database.scalars(
        select(Task)
        .where(conditions)
        .order_by(Task.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "tasks": [task_to_summary(task) for task in tasks],
    }


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> dict[str, object]:
    task = get_owned_task(task_id, user, database)
    return task_to_dict(task)


@app.patch("/api/tasks/{task_id}")
def update_task(
    task_id: str,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> dict[str, object]:
    title = payload.title.strip()
    if not title or len(title) > 255:
        raise HTTPException(
            status_code=400,
            detail="任务名称必须为 1 到 255 个字符。",
        )

    task = get_owned_task(task_id, user, database)
    task.title = title
    task.updated_at = utc_now()
    database.commit()
    database.refresh(task)
    return task_to_dict(task)


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> Response:
    task = get_owned_task(task_id, user, database)
    if task.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="正在处理中的任务不能删除。",
        )

    if task.status == "queued":
        try:
            job = Job.fetch(task.id, connection=get_queue().connection)
            if job.get_status(refresh=True) in {"queued", "deferred"}:
                job.cancel()
        except Exception:
            pass

    delete_safe_file(Path(task.stored_path), UPLOAD_DIR)

    task_result_dir = (RESULT_DIR / task.id).resolve()
    if task_result_dir.is_relative_to(RESULT_DIR.resolve()):
        shutil.rmtree(task_result_dir, ignore_errors=True)

    database.delete(task)
    database.commit()
    return Response(status_code=204)


@app.get("/results/{task_id}/{filename}")
def result_file(
    task_id: str,
    filename: str,
    user: User = Depends(get_current_user),
    database: Session = Depends(get_db),
) -> FileResponse:
    if Path(task_id).name != task_id or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="结果文件不存在。")

    get_owned_task(task_id, user, database)

    result_root = RESULT_DIR.resolve()
    result_path = (RESULT_DIR / task_id / filename).resolve()
    if not result_path.is_relative_to(result_root):
        raise HTTPException(status_code=404, detail="结果文件不存在。")
    if not result_path.is_file():
        raise HTTPException(status_code=404, detail="结果文件不存在。")

    return FileResponse(result_path)
