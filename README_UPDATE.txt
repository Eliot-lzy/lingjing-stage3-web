本次更新内容：

1. 增加用户注册、登录、JWT Cookie 认证和退出。
2. 每个任务绑定用户，任务详情、结果图片、修改和删除均检查归属。
3. 增加历史任务列表。
4. 历史任务支持查看结果、重命名和删除。
5. 主页面创建任务后会把任务 ID 写入 URL，刷新页面可恢复任务和结果。
6. 首次注册的用户会自动接管升级前没有 owner_id 的旧任务。
7. 数据库启动时自动增加 tasks.title 和 tasks.owner_id 字段。

部署前必须在服务器 .env 中配置：

JWT_SECRET=至少32位随机字符串
JWT_EXPIRE_MINUTES=1440

服务器可用以下命令生成，不要打印密钥：

cd ~/lingjing-stage3-web
grep -q '^JWT_SECRET=' .env || printf '\nJWT_SECRET=%s\nJWT_EXPIRE_MINUTES=1440\n' "$(openssl rand -hex 32)" >> .env

更新文件后重新构建：

docker compose up -d --build
docker compose ps

首次访问会跳转到 /login。注册后会自动登录并进入对比页面。
