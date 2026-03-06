"""Config package for zonny-helper."""
from zonny_helper.config.loader import load_config
from zonny_helper.config.schema import ZonnyConfig

__all__ = ["load_config", "ZonnyConfig"]
