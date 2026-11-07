from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Lingjing Stage 3 Vision Comparison",
    version="0.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


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
    }


@app.post("/api/upload")
async def upload_image(
    image: UploadFile = File(...),
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

    upload_id = uuid.uuid4().hex
    saved_path = UPLOAD_DIR / f"{upload_id}{extension}"
    saved_path.write_bytes(contents)

    return {
        "status": "uploaded",
        "upload_id": upload_id,
        "original_name": original_name,
        "format": image_format,
        "width": width,
        "height": height,
        "size_bytes": len(contents),
        "message": "图片上传成功，模型处理接口将在下一阶段接入。",
    }