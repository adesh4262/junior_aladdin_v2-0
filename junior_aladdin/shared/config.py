"""Configuration system for Junior Aladdin.

Loads configuration from YAML files with environment variable overrides.
Supports per-environment configs (default, production, test).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from junior_aladdin.shared.errors import ConfigurationError


class Config:
    """Typed configuration accessor.

    Usage:
        config = Config()
        api_key = config.get('angel_one.api_key')
        env = config.get('env')
    """

    DEFAULTS: dict[str, Any] = {
        "env": "development",
        "angel_one": {
            "client_id": "",
            "api_key": "",
            "pin": "",
            "totp_secret": "",
        },
        "capital": {
            "paper_limit": 100000,
            "real_limit": 50000,
            "max_loss_per_trade": 5000,
        },
        "logging": {
            "level": "INFO",
            "format": "json",
            "rotation": "1 day",
        },
        "paths": {
            "data_dir": "data/",
            "log_dir": "logs/",
            "replay_dir": "data/replay/",
        },
        "thresholds": {
            "confidence_min": 0.6,
            "conviction_min": 60,
            "freshness_max_age_seconds": 300,
        },
    }

    ENV_VAR_MAP: dict[str, str] = {
        "angel_one.client_id": "ANGEL_ONE_CLIENT_ID",
        "angel_one.api_key": "ANGEL_ONE_API_KEY",
        "angel_one.pin": "ANGEL_ONE_PIN",
        "angel_one.totp_secret": "ANGEL_ONE_TOTP_SECRET",
        "env": "ENV",
        "capital.paper_limit": "CAPITAL_PAPER_LIMIT",
        "capital.real_limit": "CAPITAL_REAL_LIMIT",
        "capital.max_loss_per_trade": "CAPITAL_MAX_LOSS_PER_TRADE",
    }

    def __init__(
        self,
        env: str | None = None,
        config_dir: str | Path | None = None,
        load_dotenv: bool = True,
    ) -> None:
        self._data: dict[str, Any] = dict(self.DEFAULTS)
        self._config_dir = Path(config_dir) if config_dir else Path("config")
        self._dotenv_values: dict[str, str] = {}

        # Load .env file into instance-level dict only (NOT os.environ)
        if load_dotenv:
            self._load_dotenv()

        # Determine environment: explicit > system env > .env > default
        self._env = env or os.getenv("ENV") or self._dotenv_values.get("ENV", "development")

        # Load YAML config files
        self._load_yaml("default.yaml")
        if self._env != "development":
            self._load_yaml(f"{self._env}.yaml")

        # Override with env vars (instance .env values first, then system env)
        self._load_env_vars()

    def _load_yaml(self, filename: str) -> None:
        """Load a YAML config file and merge into current data."""
        filepath = self._config_dir / filename
        if not filepath.exists():
            return
        try:
            with open(filepath) as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict):
                self._deep_merge(self._data, data)
        except Exception as e:
            raise ConfigurationError(
                f"Failed to load config file: {filepath}",
                details={"filename": filename, "path": str(filepath)},
                original_exception=e,
            )

    def _load_dotenv(self) -> None:
        """Load .env file from project root into self._dotenv_values only.

        Parses KEY=VALUE format lines, skips comments (#) and empty lines.
        Removes optional quotes around values.
        Does NOT write to os.environ to avoid polluting other Config instances.
        """
        env_path = Path(".env")
        if not env_path.exists():
            return
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove surrounding quotes if present
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    if key:
                        self._dotenv_values[key] = value
        except Exception as e:
            raise ConfigurationError(
                "Failed to load .env file",
                details={"path": str(env_path)},
                original_exception=e,
            )

    def _load_env_vars(self) -> None:
        """Override config values from environment variables.

        Priority: system env vars > .env file > YAML > defaults.
        This ensures Config(load_dotenv=False) is fully isolated from
        any .env file values.
        """
        for config_key, env_var in self.ENV_VAR_MAP.items():
            # System environment variables have highest priority
            value = os.getenv(env_var)
            if value is None:
                # Fall back to .env file values (instance-level only)
                value = self._dotenv_values.get(env_var)
            if value is not None:
                self._set_nested(self._data, config_key, self._coerce_value(value))

    @staticmethod
    def _coerce_value(value: str) -> str | int | float | bool:
        """Coerce env var string to appropriate type."""
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        """Recursively merge override dict into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._deep_merge(base[key], value)
            else:
                base[key] = value

    @staticmethod
    def _set_nested(d: dict, key_path: str, value: Any) -> None:
        """Set a nested dict value using dot notation key path."""
        keys = key_path.split(".")
        current = d
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get config value using dot notation.

        Args:
            key_path: Dot-separated path (e.g., 'angel_one.api_key')
            default: Default value if key not found

        Returns:
            Config value, or default if key not found
        """
        keys = key_path.split(".")
        current = self._data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return default
            else:
                return default
        return current

    @property
    def env(self) -> str:
        """Current environment name."""
        return self._env

    def validate_required(self) -> None:
        """Validate that all required config values are present.

        Raises ConfigurationError if any required value is missing.
        """
        required_keys = [
            "angel_one.client_id",
            "angel_one.api_key",
            "angel_one.pin",
        ]
        missing = []
        for key in required_keys:
            if not self.get(key):
                missing.append(key)
        if missing:
            raise ConfigurationError(
                "Missing required configuration values",
                details={"missing_keys": missing},
            )
