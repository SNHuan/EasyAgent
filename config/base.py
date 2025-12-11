from pathlib import Path
from typing import Any, Self

import litellm
import yaml
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).parent
DEFAULT_CONFIG = CONFIG_DIR / "config.yaml"


class BaseConfig(BaseModel):
    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> Self:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
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
