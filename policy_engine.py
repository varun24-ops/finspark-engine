from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from errors import PolicyValidationError
from registry import get_adapter


def normalize_backup_provider(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return normalized


def split_adapter_version(adapter_value: str | None) -> tuple[str | None, str | None]:
    if not adapter_value:
        return None, None
    if "@" not in adapter_value:
        return adapter_value, None
    return tuple(adapter_value.split("@", 1))


@dataclass(slots=True)
class PolicyEvaluation:
    service_id: str
    provider: str
    critical: bool = False
    issues: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    expected_role: str | None = None
    expected_fallback: str | None = None
    expected_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_service_policy(
    service_id: str,
    service_cfg: dict[str, Any],
    integrations: dict[str, Any],
) -> PolicyEvaluation:
    if not isinstance(service_cfg, dict):
        raise PolicyValidationError(f"Integration `{service_id}` must be a mapping.")

    service_type = str(service_cfg.get("service_type", "other"))
    provider = str(service_cfg.get("provider", "Unknown"))
    mandatory = bool(service_cfg.get("mandatory", False))
    fallback = str(service_cfg.get("fallback", "")).strip()
    configured_role = str(service_cfg.get("role", "primary")).strip()
    configured_adapter, configured_version = split_adapter_version(
        str(service_cfg.get("adapter", ""))
    )
    backup_provider = normalize_backup_provider(service_cfg.get("backup_provider"))
    registry_entry = get_adapter(provider)

    evaluation = PolicyEvaluation(service_id=service_id, provider=provider)

    if registry_entry is None:
        evaluation.issues.append(
            f"Policy breach: provider {provider} is not present in the adapter registry."
        )
        evaluation.critical = True
        return evaluation

    expected_mandatory = bool(registry_entry.get("mandatory_default", False))
    expected_fallback = str(registry_entry.get("fallback_mode", "")).strip()
    expected_role = str(registry_entry.get("role", "primary")).strip()
    expected_backup_provider = normalize_backup_provider(registry_entry.get("backup_provider"))
    expected_adapter = str(registry_entry.get("adapter", ""))
    expected_version = str(registry_entry.get("version", ""))
    available_versions = list(registry_entry.get("available_versions", [expected_version]))

    evaluation.expected_role = expected_role
    evaluation.expected_fallback = expected_fallback
    evaluation.expected_version = expected_version

    if expected_mandatory and not mandatory:
        evaluation.issues.append(
            f"Policy breach: registry marks {provider} as mandatory and runtime config cannot downgrade it."
        )
        evaluation.critical = True

    if expected_fallback and fallback != expected_fallback:
        evaluation.issues.append(
            f"Policy breach: registry requires fallback mode `{expected_fallback}` for {provider}, "
            f"but config uses `{fallback or 'none'}`."
        )
        evaluation.critical = True

    if expected_backup_provider != backup_provider:
        evaluation.issues.append(
            f"Policy breach: registry expects backup provider `{expected_backup_provider or 'none'}` "
            f"for {provider}, but config uses `{backup_provider or 'none'}`."
        )
        evaluation.critical = True

    if configured_role and configured_role != expected_role:
        evaluation.issues.append(
            f"Policy breach: registry fixes role `{expected_role}` for {provider}, "
            f"but config uses `{configured_role}`."
        )
        evaluation.critical = True

    if configured_adapter and configured_adapter != expected_adapter:
        evaluation.issues.append(
            f"Policy breach: registry requires adapter `{expected_adapter}` for {provider}, "
            f"but config uses `{configured_adapter}`."
        )
        evaluation.critical = True

    if configured_version and configured_version not in available_versions:
        evaluation.issues.append(
            f"Policy breach: version `{configured_version}` for {provider} is not in the "
            f"registry-approved set {available_versions}."
        )
        evaluation.critical = True
    elif configured_version and expected_version and configured_version != expected_version:
        evaluation.advisories.append(
            f"Version advisory: {provider} is using `{configured_version}` while the latest "
            f"approved version is `{expected_version}`."
        )

    if fallback == "use_backup" and not backup_provider:
        evaluation.issues.append("Policy breach: use_backup fallback requires a configured backup provider.")
        evaluation.critical = True

    if service_type == "kyc" and not mandatory:
        evaluation.issues.append("Policy breach: KYC must remain mandatory.")
        evaluation.critical = True

    if service_type == "bank_verify" and not mandatory:
        evaluation.issues.append("Policy breach: bank verification must remain mandatory.")
        evaluation.critical = True

    if service_type == "credit_bureau" and not mandatory:
        evaluation.issues.append(
            "Policy breach: credit bureau checks must be mandatory before loan decisioning."
        )
        evaluation.critical = True

    referenced_as_backup = any(
        other_id != service_id
        and str(other_cfg.get("service_type", "other")) == service_type
        and normalize_backup_provider(other_cfg.get("backup_provider")) == provider
        for other_id, other_cfg in integrations.items()
    )
    if expected_role == "fallback" and not referenced_as_backup:
        evaluation.issues.append(
            f"Policy breach: {provider} is configured as a standalone {service_type} "
            "integration even though it is already modeled as another provider's fallback."
        )
        evaluation.critical = True

    return evaluation


def evaluate_config_policies(config_payload: dict[str, Any]) -> list[PolicyEvaluation]:
    integrations = config_payload.get("integrations", {})
    if not isinstance(integrations, dict):
        raise PolicyValidationError("Config must contain an `integrations` mapping.")
    return [
        evaluate_service_policy(service_id, service_cfg, integrations)
        for service_id, service_cfg in integrations.items()
    ]
