# Happy Family

> **让每一天的牵挂，都变成可追的温暖故事**

---

## 这是什么

**Happy Family** ：一个 **情感翻译器**：把你忙碌、粗糙的日常（日程 + 碎片），翻译成关心你的人（父母、伴侣、朋友）能看懂、能感受到的画面和故事。

- 一句话钩子：**"让每一天的牵挂，都变成可追的温暖故事"**
- 破圈表达：**"让关心你的人能轻松、具像化地了解你。"**

---

## 快速开始

需要 Python 3、`pip3`、Node.js 和 npm。数据库、上传文件与账号都只保存在本机；项目不会自动创建演示账号。

### 本地完整体验

```bash
# 1. 后端配置
cd src/engine
cp .env.example .env
# 编辑 .env，填写 DIARY_API_KEY 和 IMAGE_API_KEY

# 2. 安装并启动后端
pip3 install -r requirements.txt
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 3. 启动前端（另开终端）
cd src/app/frontend
npm install
npm run dev
# 浏览器打开 http://localhost:3000
```

日记生成需要 `DIARY_API_BASE_URL`、`DIARY_API_KEY`、`DIARY_MODEL`；图片生成需要 `IMAGE_API_BASE_URL`、`IMAGE_API_KEY`、`IMAGE_MODEL`。API Key 只放本地 `src/engine/.env`，不要提交到 Git。缺失配置时相应接口会返回明确的 `503`，其余私有记录功能仍可使用。

本地 HTTP 开发使用 `SESSION_COOKIE_SECURE=false`；线上 HTTPS 必须改为 `true`。登录态使用 HttpOnly、SameSite=Lax Cookie，前端请求不传 `user_id`。`FRONTEND_ORIGINS` 必须填写实际前端源，不能使用 `*`。

### 手动建立双人演示数据

1. 使用两个独立浏览器资料或普通窗口 + 无痕窗口，分别注册 Alice、Bob 两个新账号。
2. Alice 在「我的」中创建房间并生成分享码；Bob 输入分享码加入。
3. Alice 在「记录」中添加日程/碎片并完成日记，选择图片后明确发布到「我们」。
4. Bob 在「我们」中查看、点赞和评论；温度也需要各自主动分享。

数据库默认从空状态迁移，不会自动写入演示用户、房间或隐私记录。需要重置本地演示环境时，请停止服务后自行备份并更换 `ZHIJI_DB_PATH`/`ZHIJI_UPLOAD_DIR` 到新的空路径；不要提交 `.env`、数据库或上传目录。

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
