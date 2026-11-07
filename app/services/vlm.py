from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import cv2
from json_repair import repair_json
from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)


DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_MODEL = "glm-4.6v-flash"
FALLBACK_MODEL = "glm-4v-flash"

PROMPT = """
你是桌面物品清点助手。只根据图片中清晰可见的内容回答。

只输出一个 JSON 对象，不要输出 Markdown。
格式：
{
  "scene_summary": "一句话场景描述",
  "items": [
    {
      "name": "物品名称",
      "count": 1,
      "location": "画面中的大致位置",
      "evidence": "可见的判断依据"
    }
  ],
  "total_objects": 1,
  "uncertain_items": [],
  "notes": []
}

约束：
- items 最多 10 项；
- total_objects 必须等于所有 count 字段之和；
- 不猜测被完全遮挡或无法确认的物品；
- 不使用未转义的引号或换行。
""".strip()


def encode_image(image_path: Path, max_side: int = 1280) -> tuple[str, int, int]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")

    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))

    if scale < 1.0:
        image = cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )

    height, width = image.shape[:2]
    success, encoded = cv2.imencode(
        ".jpg",
        image,
        [int(cv2.IMWRITE_JPEG_QUALITY), 88],
    )
    if not success:
        raise RuntimeError("图片编码失败")

    payload = base64.b64encode(encoded.tobytes()).decode("utf-8")
    return f"data:image/jpeg;base64,{payload}", width, height


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    if start < 0:
        raise ValueError(f"模型没有返回 JSON:\n{text}")

    end = cleaned.rfind("}")
    candidate = cleaned[start : end + 1] if end > start else cleaned[start:]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(repair_json(candidate))

    if not isinstance(parsed, dict):
        raise ValueError("模型返回结果不是 JSON 对象")

    return parsed


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif hasattr(part, "text"):
                parts.append(str(part.text))
        return "\n".join(parts).strip()

    return str(content)


def usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return None


def model_candidates(primary_model: str) -> list[str]:
    models = [primary_model]
    if primary_model != FALLBACK_MODEL:
        models.append(FALLBACK_MODEL)
    return models


def max_tokens_for_model(model_name: str) -> int:
    if model_name == FALLBACK_MODEL:
        return 1024
    return 4096


def describe_image(image_path: Path, output_dir: Path) -> dict[str, Any]:
    api_key = os.getenv("ZHIPU_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("服务器未配置 ZHIPU_API_KEY")

    if not api_key.isascii():
        raise RuntimeError("ZHIPU_API_KEY 包含非 ASCII 字符")

    base_url = os.getenv("ZHIPU_BASE_URL", DEFAULT_BASE_URL).strip()
    primary_model = os.getenv("ZHIPU_VLM_MODEL", DEFAULT_MODEL).strip()

    image_data_url, sent_width, sent_height = encode_image(image_path)

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=90.0,
        max_retries=0,
    )

    start_time = time.perf_counter()
    response = None
    used_model = ""
    errors: list[str] = []

    for model_name in model_candidates(primary_model):
        token_limit = max_tokens_for_model(model_name)

        for attempt in range(1, 4):
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是严谨的图像观察助手，"
                                "只回答图片中可见的内容。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_data_url},
                                },
                                {"type": "text", "text": PROMPT},
                            ],
                        },
                    ],
                    temperature=0.1,
                    max_tokens=token_limit,
                )
                used_model = model_name
                break
            except (RateLimitError, APITimeoutError, APIConnectionError) as error:
                errors.append(f"{model_name}: {error}")
                if attempt < 3:
                    time.sleep(3 * (2 ** (attempt - 1)))
            except Exception as error:
                errors.append(f"{model_name}: {error}")
                break

        if response is not None:
            break

    if response is None:
        raise RuntimeError("视觉模型请求失败: " + " | ".join(errors))

    elapsed_seconds = time.perf_counter() - start_time
    raw_text = message_text(response.choices[0].message.content)
    finish_reason = response.choices[0].finish_reason

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "multimodal_raw.txt"
    raw_path.write_text(raw_text + "\n", encoding="utf-8")

    if finish_reason == "length":
        raise RuntimeError(
            "视觉模型输出达到 Token 上限，"
            "原始响应已保存到 multimodal_raw.txt"
        )

    parsed = extract_json(raw_text)
    items = parsed.get("items", [])
    count_sum = sum(
        int(item.get("count", 0))
        for item in items
        if isinstance(item, dict)
    )

    parsed_path = output_dir / "multimodal.json"
    parsed_path.write_text(
        json.dumps(
            {
                "model": used_model,
                "result": parsed,
                "finish_reason": finish_reason,
                "usage": usage_dict(response.usage),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "model": used_model,
        "summary": parsed.get("scene_summary", ""),
        "items": items,
        "total_objects": parsed.get("total_objects", count_sum),
        "item_count_sum": count_sum,
        "uncertain_items": parsed.get("uncertain_items", []),
        "notes": parsed.get("notes", []),
        "image_width_sent": sent_width,
        "image_height_sent": sent_height,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "finish_reason": finish_reason,
        "usage": usage_dict(response.usage),
        "raw_response_file": raw_path.name,
        "parsed_result_file": parsed_path.name,
    }