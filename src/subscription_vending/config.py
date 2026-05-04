# Backward-compatible re-export -- Settings and get_settings have moved to core.config.
from .core.config import Settings as Settings, get_settings as get_settings  # noqa: F401
