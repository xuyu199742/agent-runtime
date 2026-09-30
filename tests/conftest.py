import os

# V0.1 兼容测试显式开启旧 API；服务默认关闭旧入口。
os.environ.setdefault("LEGACY_API_ENABLED", "true")
