import os
from pathlib import Path
from typing import Any, Self

import litellm
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

# 加载 .env 文件（项目根目录或当前工作目录）
load_dotenv()

CONFIG_DIR = Path(__file__).parent


def _get_default_config() -> Path:
    """优先读取环境变量 DEFAULT_CONFIG，否则使用包内默认配置"""
    if env_path := os.getenv("EA_DEFAULT_CONFIG"):
        return Path(env_path).expanduser().resolve()
    return CONFIG_DIR / "config.yaml"


class BaseConfig(BaseModel):
    @classmethod
    def load(cls, path: str | Path | None = None) -> Self:
        config_path = Path(path) if path else _get_default_config()
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)


_app_config: "AppConfig | None" = None


class AppConfig(BaseConfig):
    """全局应用配置"""

    debug: bool = False
    summary_model: str | None = None

    @classmethod
    def get(cls) -> "AppConfig":
        global _app_config
        if _app_config is None:
            _app_config = cls.load()
        return _app_config

    @classmethod
    def reset(cls) -> None:
        global _app_config
        _app_config = None


def get_summary_model(fallback: str = "gpt-4o") -> str:
    """获取 summary 模型名称，未配置则使用 fallback"""
    return AppConfig.get().summary_model or fallback


class ModelConfig(BaseConfig):
    models: dict[str, dict[str, Any]] = {}

    def get_model(self, name: str) -> dict:
        if name not in self.models:
            raise KeyError(f"Model '{name}' not found")

        cfg = self.models[name]
        api_type = cfg.get("api_type", "openai")
        model_name = f"{api_type}/{name}"

        if cost := cfg.get("cost"):
            litellm.register_model({model_name: {"litellm_provider": api_type, **cost}})

        return {
            "model": model_name,
            "api_base": cfg.get("base_url"),
            "api_key": cfg.get("api_key"),
        }


def is_debug() -> bool:
    """快捷方法：检查是否开启 debug 模式"""
    return AppConfig.get().debug
