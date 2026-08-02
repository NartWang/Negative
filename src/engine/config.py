import os
from dotenv import load_dotenv

load_dotenv()

# 日记 Agent
DIARY_API_BASE_URL = os.getenv("DIARY_API_BASE_URL", "")
DIARY_API_KEY = os.getenv("DIARY_API_KEY", "")
DIARY_MODEL = os.getenv("DIARY_MODEL", "glm-5.1")

# 绘图 Agent
IMAGE_API_BASE_URL = os.getenv("IMAGE_API_BASE_URL", "")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "qwen-image-2512-lightning")

# 邮件配置
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "你的知己")

# 分享链接基础 URL（部署后设为实际域名）
SHARE_BASE_URL = os.getenv("SHARE_BASE_URL", "http://localhost:8000")

# 服务配置
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
