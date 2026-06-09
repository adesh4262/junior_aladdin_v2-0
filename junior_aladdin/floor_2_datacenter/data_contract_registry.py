"""Floor 2 Data Contract Registry — first-class governance for all feed contracts.

Provides the **DataContractRegistry** class that manages registered feed
contracts with runtime lookup, validation, and enforcement hooks.

Responsibilities:
- **Register contracts**: Add ``FeedContract`` definitions to the registry.
- **Lookup**: Get contract by feed name, list all contracts.
- **Validate**: Check data dicts against a registered contract's schema.
- **Enforcement**: Raise ``ContractViolationError`` on critical mismatches.
- **Lifecycle**: Add, update, remove, clear contracts at runtime.

Architecture rules:
- Contracts are first-class governance — ALL feeds must have a registered contract.
- Runtime contract checks prevent silent data quality degradation.
- Unknown feeds get a default MINOR contract (not rejected).
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    DataClass,
    FeedContract,
)
from junior_aladdin.shared.errors import ContractViolationError
from junior_aladdin.shared.logging import get_logger

logger = get_logger("data_contract_registry")

# Mapping of type strings to Python type names for validation
_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
    "any": object,
}


class DataContractRegistry:
    """Central registry for all feed contracts.

    Thread-safe. Supports runtime registration, lookup, validation, and
    enforcement of data contracts.

    Typical usage::

        registry = DataContractRegistry()
        registry.register(FeedContract(name="spot_tick", ...))
        contract = registry.get("spot_tick")
        errors = registry.validate_data("spot_tick", {"ltp": 18500.0})
        registry.enforce("spot_tick", {"ltp": 18500.0})  # raises on violation
    """

    def __init__(self) -> None:
        self._lock = Lock()
        # name -> FeedContract
        self._contracts: dict[str, FeedContract] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, contract: FeedContract) -> None:
        """Register a feed contract.

        If a contract with the same name already exists, it is overwritten
        and a warning is logged.

        Args:
            contract: The ``FeedContract`` to register.
        """
        with self._lock:
            name = contract.name
            if name in self._contracts:
                logger.warning(
                    "Overwriting existing contract",
                    extra={"contract_name": name},
                )
            self._contracts[name] = contract

        logger.debug("Contract registered", extra={"contract_name": name, "fields": len(contract.schema_fields)})

    def register_many(self, contracts: list[FeedContract]) -> int:
        """Register multiple feed contracts at once.

        Args:
            contracts: List of ``FeedContract`` instances.

        Returns:
            Number of contracts registered.
        """
        for c in contracts:
            self.register(c)
        return len(contracts)

    def update(self, name: str, **updates: Any) -> bool:
        """Update specific fields of an existing contract.

        Args:
            name: The contract name to update.
            **updates: Field names and new values (e.g., ``freshness_expectation_s=60``).

        Returns:
            ``True`` if updated, ``False`` if contract not found.
        """
        with self._lock:
            contract = self._contracts.get(name)
            if contract is None:
                return False
            for key, value in updates.items():
                if hasattr(contract, key):
                    setattr(contract, key, value)
        logger.info("Contract updated", extra={"contract_name": name, "updates": list(updates)})
        return True

    def remove(self, name: str) -> bool:
        """Remove a contract from the registry.

        Args:
            name: The contract name to remove.

        Returns:
            ``True`` if removed, ``False`` if not found.
        """
        with self._lock:
            if name in self._contracts:
                del self._contracts[name]
                logger.debug("Contract removed", extra={"contract_name": name})
                return True
            return False

    def clear(self) -> None:
        """Remove ALL contracts from the registry."""
        with self._lock:
            self._contracts.clear()
        logger.info("DataContractRegistry cleared")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> FeedContract | None:
        """Get a contract by name.

        Args:
            name: The contract name (e.g., ``\"spot_tick\"``).

        Returns:
            The ``FeedContract``, or ``None`` if not found.
        """
        with self._lock:
            return self._contracts.get(name)

    def get_or_default(self, name: str) -> FeedContract:
        """Get a contract by name, or return a default MINOR contract.

        Args:
            name: The contract name.

        Returns:
            The ``FeedContract`` if found, or a default MINOR contract.
        """
        contract = self.get(name)
        if contract:
            return contract
        return FeedContract(
            name=name,
            ownership="Unknown",
            data_class=DataClass.MINOR,
            description=f"Default contract for unknown feed: {name}",
        )

    def list_contracts(self) -> list[FeedContract]:
        """List all registered contracts.

        Returns:
            List of ``FeedContract`` instances, sorted by name.
        """
        with self._lock:
            return sorted(self._contracts.values(), key=lambda c: c.name)

    def count(self) -> int:
        """Get the number of registered contracts.

        Returns:
            Contract count.
        """
        with self._lock:
            return len(self._contracts)

    def has(self, name: str) -> bool:
        """Check if a contract is registered.

        Args:
            name: The contract name.

        Returns:
            ``True`` if registered.
        """
        with self._lock:
            return name in self._contracts

    def get_names(self) -> list[str]:
        """Get all registered contract names.

        Returns:
            Sorted list of contract names.
        """
        with self._lock:
            return sorted(self._contracts.keys())

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_data(
        self,
        name: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Validate a data dict against a registered contract's schema.

        Checks:
        - All mandatory schema fields are present.
        - Field types match the contract's expected types.

        Args:
            name: The contract name to validate against.
            data: The data dict to validate.

        Returns:
            List of validation error dicts. Empty list if valid.
            Each error has ``field``, ``expected``, and ``actual`` keys.
        """
        contract = self.get_or_default(name)
        errors: list[dict[str, Any]] = []

        for field, expected_type in contract.schema_fields.items():
            actual_value = data.get(field)

            # Check missing field
            if actual_value is None:
                errors.append({
                    "field": field,
                    "expected": expected_type,
                    "actual": "missing",
                    "message": f"Missing required field: {field}",
                })
                continue

            # Check type mismatch
            expected_py_type = _TYPE_MAP.get(expected_type, object)
            if expected_py_type is not object and not isinstance(actual_value, expected_py_type):
                errors.append({
                    "field": field,
                    "expected": expected_type,
                    "actual": type(actual_value).__name__,
                    "message": f"Field {field!r}: expected {expected_type}, got {type(actual_value).__name__}",
                })

        return errors

    def validate_data_strict(
        self,
        name: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Validate data with strict mode — also flags extra unknown fields.

        Args:
            name: The contract name.
            data: The data dict.

        Returns:
            List of validation errors (including unknown field warnings).
        """
        errors = self.validate_data(name, data)
        contract = self.get_or_default(name)

        # Flag extra fields not in the schema
        known_fields = set(contract.schema_fields.keys())
        extra_fields = set(data.keys()) - known_fields
        for field in sorted(extra_fields):
            errors.append({
                "field": field,
                "expected": "not in schema",
                "actual": type(data[field]).__name__ if data[field] is not None else "None",
                "message": f"Unexpected field: {field}",
            })

        return errors

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def enforce(self, name: str, data: dict[str, Any]) -> None:
        """Validate data and raise ``ContractViolationError`` on failure.

        Args:
            name: The contract name.
            data: The data dict to validate.

        Raises:
            ContractViolationError: If the data fails contract validation.
        """
        errors = self.validate_data(name, data)
        if errors:
            msg = f"Contract violation for {name!r}: {len(errors)} error(s)"
            logger.warning(msg, extra={"contract_name": name, "errors": errors})
            raise ContractViolationError(msg, details={"contract_name": name, "errors": errors})

    def enforce_strict(self, name: str, data: dict[str, Any]) -> None:
        """Validate data with strict mode and raise on any issue.

        Args:
            name: The contract name.
            data: The data dict.

        Raises:
            ContractViolationError: If the data fails strict validation.
        """
        errors = self.validate_data_strict(name, data)
        if errors:
            msg = f"Strict contract violation for {name!r}: {len(errors)} error(s)"
            logger.warning(msg, extra={"contract_name": name, "errors": errors})
            raise ContractViolationError(msg, details={"contract_name": name, "errors": errors})

    def check_freshness(self, name: str, age_s: float) -> bool:
        """Check if data freshness meets the contract's expectation.

        Args:
            name: The contract name.
            age_s: Age of the data in seconds.

        Returns:
            ``True`` if fresh enough, ``False`` if stale.
        """
        contract = self.get(name)
        if contract is None:
            return True  # Unknown contract, can't enforce
        return age_s <= contract.freshness_expectation_s

    def check_source(self, name: str, source: str) -> bool:
        """Check if a source is expected for a given contract.

        Args:
            name: The contract name.
            source: The source name to check.

        Returns:
            ``True`` if the source is expected or no expectations set.
        """
        contract = self.get(name)
        if contract is None or not contract.source_expectations:
            return True  # No expectations = no restriction
        return source in contract.source_expectations

    def report(self) -> dict[str, Any]:
        """Generate a summary report of all registered contracts.

        Returns:
            Dict with contract count, names, and basic metadata.
        """
        contracts = self.list_contracts()
        return {
            "count": len(contracts),
            "names": [c.name for c in contracts],
            "major_count": sum(1 for c in contracts if c.data_class == DataClass.MAJOR),
            "minor_count": sum(1 for c in contracts if c.data_class == DataClass.MINOR),
            "contracts": [
                {
                    "name": c.name,
                    "ownership": c.ownership,
                    "data_class": c.data_class.value,
                    "fields": len(c.schema_fields),
                    "freshness_s": c.freshness_expectation_s,
                    "sources": c.source_expectations,
                }
                for c in contracts
            ],
        }
