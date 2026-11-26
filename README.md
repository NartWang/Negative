# 底片

> **把零散日常，冲洗成一集有人追更的人生剧**

---

## 这是什么

**底片**：一个 AI 辅助的个人叙事空间。你把忙碌、粗糙的日常（日程 + 碎片）随手记下，底片帮你把它们"冲洗"成日记、绘本、漫剧和时光故事——自己收藏，也可以主动分享给关心你的人（父母、伴侣、朋友），让他们能轻松、具像化地看见你的生活。

- 一句话钩子：**"把零散日常，冲洗成一集有人追更的人生剧"**
- 破圈表达：**"让关心你的人能轻松、具像化地了解你。"**
- 主结构：**记录 / 底片夹 / 回响 / 我的**。
  - **记录**：日程 + 碎片，一天结束生成日记。
  - **底片夹**：日记显影成绘本、漫剧、时光故事，按作品归档。
  - **回响**：把完成的作品发布给指定的人，对方点赞、评论，并按人物自动收录——不需要先建立双人空间。
  - **我的**：角色形象、订阅关系、账号。

---

## 快速开始

需要 Python 3、`pip3`、Node.js 和 npm。数据库、上传文件与账号都只保存在本机；项目不会自动创建演示账号。

### 本地完整体验

```bash
# 1. 后端配置
cd src/engine
cp .env.example .env
```

编辑本地 `.env`，填写以下占位配置：

```dotenv
DIARY_API_BASE_URL=<compatible-base-url>
DIARY_API_KEY=<main-text-key>
DIARY_MODEL=claude-opus-4-6
IMAGE_API_KEYS=<main-image-key>,<secondary-1>,...,<secondary-8>
```

图片 Key 池共用 `.env.example` 既有的 `IMAGE_API_BASE_URL` / `IMAGE_MODEL`；`IMAGE_API_KEY` 仅作 Key 池缺失时的 legacy fallback。

```bash
# 2. 安装并启动后端
pip3 install -r requirements.txt
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 3. 启动前端（另开终端）
cd src/app/frontend
npm install
npm run dev
# 浏览器打开 http://localhost:3000
```

日记生成需要 `DIARY_API_BASE_URL`、`DIARY_API_KEY`、`DIARY_MODEL`。`DIARY_API_BASE_URL` 必须填写支持所配模型的 OpenAI-compatible endpoint。API Key 只放本地 `src/engine/.env`，不要提交到 Git。缺失配置时相应接口会返回明确的 `503`，其余私有记录功能仍可使用。

本地 HTTP 开发使用 `SESSION_COOKIE_SECURE=false`；线上 HTTPS 必须改为 `true`。登录态使用 HttpOnly、SameSite=Lax Cookie，前端请求不传 `user_id`。`FRONTEND_ORIGINS` 必须填写实际前端源，不能使用 `*`。

### 可选：体验回响

1. 使用两个独立浏览器资料或普通窗口 + 无痕窗口，分别注册 Alice、Bob 两个新账号。
2. Alice 在「记录」中添加日程/碎片，完成日记并生成作品。
3. Alice 在「底片夹」中打开已完成作品，点击「发布到回响」，**并勾选要授权的观看者**（默认不授权任何人，需主动选择）。
4. Alice 会在「回响 → 动态」看到自己的发布；被授权的 Bob 会在动态看到该作品并点赞、评论。
5. Bob 可以在「回响 → 收录 → 他们的故事」按人物回看 Alice 当前授权给他的作品。

未发布作品、原始日记、草稿、生成提示词和 owner-only 源数据不会对观看者开放。数据库默认从空状态迁移，不会自动写入演示用户或隐私记录。需要重置本地演示环境时，请停止服务后自行备份并更换 `ZHIJI_DB_PATH`/`ZHIJI_UPLOAD_DIR` 到新的空路径；不要提交 `.env`、数据库或上传目录。

### 对外 Demo（给他人体验）

把产品交给别人体验时，为防止被无限刷取消耗 token，内置了两道开关：

**1. 关闭公开注册**——只放行你预建的体验账号登录，陌生人无法注册。在 `.env` 里加：

```dotenv
REGISTRATION_OPEN=false
```

然后用下面的清洗/注册流程预建账号（开发期 `REGISTRATION_OPEN` 默认为 `true`，本地注册不受影响）。

**2. 生成配额**——绘本 / 漫剧的"新建任务"按账号计次，默认 0（不能生成），按体验次数充值。同一任务的失败重试/重复点击不重复扣次。日记 AI 生成消耗很小，不计入配额。

```bash
# 给账号 demo01 充值:绘本 3 次、漫剧 2 次
python3 scripts/set_generation_quota.py demo01 --picturebook 3 --motion-comic 2
# 累加 / 查看
python3 scripts/set_generation_quota.py demo01 --picturebook +1
python3 scripts/set_generation_quota.py --show
```

**3. 体验结束后清理账号数据**——删除指定账号的全部数据库记录和上传/生成的媒体文件。默认 dry-run 只预览，加 `--yes` 才真正删除：

```bash
python3 scripts/reset_demo_accounts.py demo01 demo02          # 预览
python3 scripts/reset_demo_accounts.py demo01 demo02 --yes    # 执行
```

### 后端测试

```bash
cd src/engine
pip3 install -r requirements.txt -r requirements-dev.txt
PYTHONPYCACHEPREFIX=/private/tmp/hackathon-pycache python3 -m pytest -q
```

### 前端测试与生产构建

```bash
cd src/app/frontend
npm install
npm test -- --run
npm run build
```
