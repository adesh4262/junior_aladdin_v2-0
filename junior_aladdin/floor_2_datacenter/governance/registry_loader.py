"""Floor 2 Governance — registry loader.

Provides the **RegistryLoader** utility that populates a
``DataContractRegistry`` with contracts from default definitions or
configurable sources.

Responsibilities:
- **Default loading**: Load the standard set of feed contracts.
- **Config loading**: Load contracts from a config dict (for hot-reload).
- **Validation**: Verify loaded contracts have all mandatory fields.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.data_contract_registry import (
    DataContractRegistry,
)
from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    default_feed_contracts,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    DataClass,
    FeedContract,
)
from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.logging import get_logger

logger = get_logger("registry_loader")

# Mandatory fields that every FeedContract must have
_MANDATORY_CONTRACT_FIELDS = frozenset({"name", "ownership", "data_class"})


class RegistryLoader:
    """Loads feed contracts into a ``DataContractRegistry``.

    Typical usage::

        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        count = loader.load_defaults()
        count = loader.load_from_config(config_dict)
    """

    def __init__(self, registry: DataContractRegistry) -> None:
        """Initialise the loader with a registry instance.

        Args:
            registry: The ``DataContractRegistry`` to load into.
        """
        self._registry = registry

    # ------------------------------------------------------------------
    # Default Loading
    # ------------------------------------------------------------------

    def load_defaults(self) -> int:
        """Load the default set of feed contracts from ``datacenter_contracts.py``.

        Returns:
            Number of contracts loaded.
        """
        contracts = default_feed_contracts()
        count = self._registry.register_many(contracts)
        logger.info(
            "Default contracts loaded",
            extra={"count": count},
        )
        return count

    def load_minimal(self) -> int:
        """Load a minimal set of contracts (spot_tick + options_snapshot only).

        Useful for tests or dev environments.

        Returns:
            Number of contracts loaded.
        """
        from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
            default_feed_contracts,
        )
        all_contracts = default_feed_contracts()
        minimal_names = {"spot_tick", "options_snapshot"}
        minimal = [c for c in all_contracts if c.name in minimal_names]
        count = self._registry.register_many(minimal)
        logger.info("Minimal contracts loaded", extra={"count": count})
        return count

    # ------------------------------------------------------------------
    # Config Loading
    # ------------------------------------------------------------------

    def load_from_config(self, config: list[dict[str, Any]]) -> int:
        """Load contracts from a config dict list.

        Each dict should have keys matching ``FeedContract`` fields:
        ``name``, ``ownership``, ``schema_fields``, ``freshness_expectation_s``,
        ``source_expectations``, ``data_class``, ``consumers``, ``description``.

        Args:
            config: List of contract config dicts.

        Returns:
            Number of contracts loaded.

        Raises:
            ContractViolationError: If a contract config is missing mandatory fields.
        """
        contracts: list[FeedContract] = []
        for item in config:
            self._validate_config_item(item)
            contract = self._config_to_contract(item)
            contracts.append(contract)

        count = self._registry.register_many(contracts)
        logger.info("Contracts loaded from config", extra={"count": count})
        return count

    def load_from_config_safe(self, config: list[dict[str, Any]]) -> int:
        """Load contracts from config, skipping invalid items with a warning.

        Unlike ``load_from_config``, this does NOT raise an error on invalid
        items — it logs a warning and skips them.

        Args:
            config: List of contract config dicts.

        Returns:
            Number of successfully loaded contracts.
        """
        contracts: list[FeedContract] = []
        skipped = 0

        for item in config:
            try:
                self._validate_config_item(item)
                contract = self._config_to_contract(item)
                contracts.append(contract)
            except (ContractViolationError, ValueError, TypeError) as exc:
                logger.warning(
                    "Skipping invalid contract config",
                    extra={"error": str(exc), "item": item},
                )
                skipped += 1

        count = self._registry.register_many(contracts)
        if skipped:
            logger.warning(
                "Contracts loaded with skipped items",
                extra={"loaded": count, "skipped": skipped},
            )
        return count

    # ------------------------------------------------------------------
    # Hot-Reload Support
    # ------------------------------------------------------------------

    def reload_defaults(self) -> int:
        """Clear the registry and reload default contracts.

        Returns:
            Number of contracts loaded.
        """
        self._registry.clear()
        return self.load_defaults()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_config_item(item: dict[str, Any]) -> None:
        """Validate a config dict has all mandatory fields."""
        missing = _MANDATORY_CONTRACT_FIELDS - set(item.keys())
        if missing:
            raise ContractViolationError(
                f"Contract config missing mandatory fields: {missing}",
                details={
                    "contract_name": item.get("name", "unknown"),
                    "errors": [{"field": f, "message": f"Missing mandatory field: {f}"} for f in missing],
                },
            )

    @staticmethod
    def _config_to_contract(item: dict[str, Any]) -> FeedContract:
        """Convert a config dict to a FeedContract instance."""
        data_class_str = item.get("data_class", "MINOR")
        data_class = DataClass.MAJOR if data_class_str == "MAJOR" else DataClass.MINOR

        return FeedContract(
            name=str(item["name"]),
            ownership=str(item.get("ownership", "Unknown")),
            schema_fields=dict(item.get("schema_fields", {})),
            freshness_expectation_s=float(item.get("freshness_expectation_s", 300.0)),
            source_expectations=list(item.get("source_expectations", [])),
            data_class=data_class,
            consumers=list(item.get("consumers", [])),
            description=str(item.get("description", "")),
        )

    @property
    def registry(self) -> DataContractRegistry:
        """Get the underlying registry instance."""
        return self._registry
