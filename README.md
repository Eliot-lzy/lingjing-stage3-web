# 灵境第三阶段视觉方案对比 Web 应用

本项目复用第二阶段的桌面物品视觉对比任务，将 YOLO 目标检测、
MobileSAM 提示式分割和视觉语言模型接入 FastAPI Web 应用，并通过
Docker Compose 部署到 Azure Ubuntu 云服务器。

用户可以在网页中上传一张桌面图片，系统会创建后台任务，并并排展示：

- YOLO + MobileSAM 的检测与分割结果
- 视觉大模型的场景摘要和物品清单

## 在线页面

```text
http://57.158.24.224
```

Azure 虚拟机自动关机后，需要先在 Azure 门户启动虚拟机。

## 主要功能

- 上传 JPG、JPEG、PNG、WEBP 图片
- 校验图片格式、内容和大小
- 使用 YOLO11n 检测桌面物品
- 使用 MobileSAM 根据 YOLO 边界框生成分割掩膜
- 使用 OpenCV 绘制边界框、掩膜和标签
- 使用智谱视觉语言模型生成结构化物品清单
- 主视觉模型限流时自动切换备用模型
- 使用 SQLAlchemy 保存任务和结果
- 使用 Redis + RQ 异步执行视觉任务
- 使用 Nginx 提供公网访问
- 使用 Docker Compose 管理全部服务

## 系统架构

```text
浏览器
  |
  v
Nginx :80
  |
  v
FastAPI Web
  |-- 上传图片
  |-- 创建任务
  |-- 查询任务状态
  |-- 展示结果图片
  |-- SQLite 任务记录
  |
  v
Redis + RQ
  |
  v
Vision Worker
  |-- YOLO11n
  |-- MobileSAM
  |-- GLM-4.6V-Flash
  |-- GLM-4V-Flash 备用模型
```

Web 容器只负责接收请求和展示结果，耗时的视觉推理由独立 Worker 执行。
Redis 负责等待队列，SQLite 保存任务状态和处理结果。

## 技术栈

| 分类 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、Uvicorn |
| 页面 | Jinja2、HTML、CSS、JavaScript |
| 数据层 | SQLAlchemy、SQLite |
| 异步任务 | Redis 7、RQ |
| 深度学习 | PyTorch 2.14.1 CPU、Torchvision 0.29.1 CPU |
| 目标检测 | Ultralytics YOLO11n |
| 图像分割 | MobileSAM |
| 多模态模型 | 智谱 GLM-4.6V-Flash、GLM-4V-Flash |
| 图像处理 | OpenCV、Pillow、NumPy |
| Web 代理 | Nginx |
| 容器 | Docker、Docker Compose |
| 服务器 | Azure Ubuntu 24.04 LTS |

## 真实运行结果

最近一次完整任务结果：

| 指标 | 结果 |
|---|---:|
| 输入图片尺寸 | 1280 × 1707 |
| YOLO 检测目标 | 5 |
| MobileSAM 分割掩膜 | 5 |
| 传统方案耗时 | 4.944 秒 |
| 大模型物品数量 | 6 |
| 大模型耗时 | 14.802 秒 |
| 实际使用模型 | glm-4v-flash |

YOLO 将显示器识别为 COCO 类别 `tv`，将水瓶识别为 `cup`。视觉大模型
使用“显示器”“水瓶”等更自然的名称，并补充了固定类别模型无法覆盖的
物品描述。

两种方案各有优势：

- YOLO + MobileSAM 提供明确的位置、边界框和像素级掩膜。
- 视觉大模型提供更开放的类别、场景摘要和自然语言描述。
- 两种方案组合使用比单独使用其中一种更完整。

## 项目结构

```text
.
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── queue.py
│   ├── tasks.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── vision.py
│   │   └── vlm.py
│   ├── static/
│   │   └── styles.css
│   └── templates/
│       └── index.html
├── data/
│   ├── app.db
│   ├── uploads/
│   └── results/
├── docs/
│   ├── project_report.md
│   ├── deployment.md
│   └── video_script.md
├── nginx/
│   └── default.conf
├── .dockerignore
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── README.md
└── requirements.txt
```

运行数据、模型权重和 `.env` 不提交到 Git。

## 服务组成

Docker Compose 启动四个服务：

| 服务 | 作用 |
|---|---|
| `nginx` | 对外提供 80 端口并反向代理 |
| `web` | FastAPI 页面、上传和任务查询 |
| `worker` | 执行 YOLO、MobileSAM 和大模型请求 |
| `redis` | 保存异步任务队列 |

`web` 和 `worker` 使用同一个 Docker 镜像，但启动命令不同。

## 环境变量

从示例文件创建：

```bash
cp .env.example .env
```

填写：

```text
ZHIPU_API_KEY=真实APIKey
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ZHIPU_VLM_MODEL=glm-4.6v-flash
REDIS_URL=redis://redis:6379/0
```

注意事项：

- `.env` 已加入 `.gitignore`
- 不要提交真实 API Key
- 不要把 `.env` 上传到 GitHub
- 不要把私钥或 API Key 发到聊天、截图或视频中

## 快速启动

首次启动：

```bash
docker compose up -d --build
```

查看服务状态：

```bash
docker compose ps
```

预期：

```text
nginx    Up
web      Up (healthy)
worker   Up
redis    Up (healthy)
```

健康检查：

```bash
curl -sS http://127.0.0.1/api/health
```

预期：

```json
{
  "status": "ok",
  "service": "lingjing-stage3-web",
  "version": "0.4.0"
}
```

浏览器访问：

```text
http://服务器公网IP
```

## 任务处理流程

1. 用户上传图片。
2. FastAPI 验证文件类型、大小和图片完整性。
3. 使用 UUID 保存上传文件。
4. SQLAlchemy 创建状态为 `queued` 的任务。
5. 任务进入 Redis 的 `vision` 队列。
6. RQ Worker 取出任务并将状态更新为 `processing`。
7. YOLO11n 执行目标检测。
8. YOLO 边界框作为 MobileSAM 提示生成掩膜。
9. OpenCV 保存检测与分割结果图。
10. 视觉大模型生成物品清单和场景摘要。
11. 任务状态更新为 `completed`。
12. 浏览器轮询接口并显示并排结果。

任务状态：

```text
queued
processing
completed
failed
```

## API

### 健康检查

```http
GET /api/health
```

### 创建任务

```http
POST /api/tasks
Content-Type: multipart/form-data
```

字段：

```text
image: 图片文件
```

### 查询任务

```http
GET /api/tasks/{task_id}
```

返回内容：

- 任务编号
- 图片尺寸
- 图片格式
- 文件大小
- 当前状态
- 传统方案结果
- 多模态方案结果
- 错误信息

### 查询结果图片

```http
GET /results/{task_id}/{filename}
```

目前传统方案结果文件名为：

```text
traditional.jpg
```

## 视觉模型回退机制

主模型：

```text
glm-4.6v-flash
```

备用模型：

```text
glm-4v-flash
```

处理策略：

- 主模型支持更高输出 Token 上限。
- 备用模型最大输出限制为 1024 Token。
- 429 限流时采用逐步增加等待时间。
- 主模型多次失败后自动切换备用模型。
- 原始响应保存为 `multimodal_raw.txt`。
- 结构化结果保存为 `multimodal.json`。
- JSON 不严格时使用 `json-repair` 修复。

## 服务器部署

当前服务器环境：

```text
Microsoft Azure
East Asia
Ubuntu 24.04.5 LTS
2 vCPU
8 GiB 内存
64 GiB SSD
无 GPU
Docker Engine 29
Docker Compose v5
```

安全组仅开放：

```text
TCP 22
TCP 80
TCP 443
```

数据库和 Redis 端口均未向公网开放。

部署步骤：

```bash
git clone https://github.com/Eliot-lzy/lingjing-stage3-web.git
cd lingjing-stage3-web
cp .env.example .env
```

在 `.env` 中填写真实配置，然后：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs --tail=100 web
docker compose logs --tail=100 worker
docker compose logs --tail=100 nginx
```

## 更新部署

拉取最新代码：

```bash
git pull
```

重新构建并启动：

```bash
docker compose up -d --build
```

健康检查：

```bash
curl -sS http://127.0.0.1/api/health
```

Nginx 使用 Docker 内置 DNS 动态解析 Web 服务，Web 容器重建后不会继续
使用旧的容器 IP。

## 常用运维命令

查看容器：

```bash
docker compose ps
```

实时查看 Web 日志：

```bash
docker compose logs -f web
```

实时查看 Worker 日志：

```bash
docker compose logs -f worker
```

查看 Redis：

```bash
docker compose exec redis redis-cli ping
```

预期：

```text
PONG
```

停止服务：

```bash
docker compose down
```

`docker compose down` 不会删除 Redis 数据卷。

## 数据持久化

宿主机目录：

```text
./data/app.db
./data/uploads/
./data/results/
```

Docker Named Volume：

```text
lingjing-stage3_redis_data
```

重建容器不会删除任务数据库、上传图片、结果图片和 Redis 队列数据。

## 安全说明

- API Key 只保存在服务器 `.env`
- SSH 使用 RSA 私钥登录
- 不开放 Redis 端口
- 不开放 SQLite 或数据库端口
- Azure 安全组只开放必要端口
- 上传文件限制为 10 MB
- 上传文件使用 UUID 命名
- 不直接信任原始文件名
- 结果文件路径经过目录穿越检查

当前结果图片通过不可预测的任务 UUID 路径访问。后续如需更严格权限，
可以增加 JWT 用户认证和任务归属检查。

## 已知限制

- YOLO 使用固定 COCO 类别，无法识别类别表以外的物品。
- 显示器容易被识别为 `tv`，水瓶容易被识别为 `cup`。
- CPU 推理速度低于 GPU。
- 免费视觉模型可能限流。
- 大模型输出名称和数量仍需要人工检查。
- 当前 Web 页面尚未加入用户登录和任务历史列表。
- Azure 虚拟机自动关机后需要先在门户启动。
- Azure 学生额度用完后可能产生费用。

## 开发命令

检查 Compose 配置：

```bash
docker compose config
```

检查 Python 依赖：

```bash
docker compose exec web python -m pip check
```

验证 PyTorch：

```bash
docker compose exec web python -c "import torch; print(torch.__version__)"
```

预期：

```text
2.14.1+cpu
```

验证 YOLO：

```bash
docker compose exec web python -c "import numpy as np; from ultralytics import YOLO; m=YOLO('yolo11n.pt'); r=m.predict(np.zeros((640,640,3),dtype=np.uint8),imgsz=640,device='cpu',verbose=False); print('yolo_ok', len(r))"
```

验证 Redis：

```bash
docker compose exec redis redis-cli ping
```

## Git 仓库

```text
https://github.com/Eliot-lzy/lingjing-stage3-web
```

## 项目文档

- 项目说明与个人感悟：`docs/project_report.md`
- 服务器部署说明：`docs/deployment.md`
- 视频录制脚本：`docs/video_script.md`

## 参考资料

- FastAPI: https://fastapi.tiangolo.com/
- SQLAlchemy: https://www.sqlalchemy.org/
- Redis: https://redis.io/
- RQ: https://python-rq.org/
- Ultralytics: https://docs.ultralytics.com/
- MobileSAM: https://github.com/ChaoningZhang/MobileSAM
- 智谱开放平台: https://bigmodel.cn/
- Docker Compose: https://docs.docker.com/compose/
- Nginx: https://nginx.org/