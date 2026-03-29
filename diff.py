from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(config_source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(config_source, dict):
        return config_source

    path = Path(config_source)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _split_adapter(adapter_value: str | None) -> tuple[str | None, str | None]:
    if not adapter_value:
        return None, None
    if "@" not in adapter_value:
        return adapter_value, None
    return tuple(adapter_value.split("@", 1))


def diff_configs(
    old_config: str | Path | dict[str, Any],
    new_config: str | Path | dict[str, Any],
) -> dict[str, Any]:
    old_payload = load_yaml_config(old_config)
    new_payload = load_yaml_config(new_config)

    old_integrations = old_payload.get("integrations", {})
    new_integrations = new_payload.get("integrations", {})

    old_keys = set(old_integrations)
    new_keys = set(new_integrations)

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed: list[dict[str, Any]] = []
    summary_lines: list[str] = []

    for service_id in added:
        svc = new_integrations[service_id]
        summary_lines.append(
            f"{service_id}: added {svc['provider']} integration using {svc['adapter']}."
        )

    for service_id in removed:
        svc = old_integrations[service_id]
        summary_lines.append(
            f"{service_id}: removed {svc['provider']} integration."
        )

    for service_id in sorted(old_keys & new_keys):
        before = old_integrations[service_id]
        after = new_integrations[service_id]
        field_changes: list[str] = []

        old_adapter_name, old_adapter_version = _split_adapter(before.get("adapter"))
        new_adapter_name, new_adapter_version = _split_adapter(after.get("adapter"))

        if before.get("provider") != after.get("provider"):
            field_changes.append(
                f"provider {before.get('provider')} -> {after.get('provider')}"
            )
            summary_lines.append(
                f"{service_id}: provider switched from {before.get('provider')} to {after.get('provider')}."
            )

        if old_adapter_name == new_adapter_name and old_adapter_version != new_adapter_version:
            field_changes.append(
                f"adapter version {old_adapter_version} -> {new_adapter_version}"
            )
            summary_lines.append(
                f"{service_id}: {new_adapter_name} moved from {old_adapter_version} to {new_adapter_version}."
            )
        elif before.get("adapter") != after.get("adapter"):
            field_changes.append(
                f"adapter {before.get('adapter')} -> {after.get('adapter')}"
            )
            summary_lines.append(
                f"{service_id}: adapter changed from {before.get('adapter')} to {after.get('adapter')}."
            )

        for field_name in ("mandatory", "timeout_ms", "fallback"):
            if before.get(field_name) != after.get(field_name):
                field_changes.append(
                    f"{field_name} {before.get(field_name)} -> {after.get(field_name)}"
                )
                summary_lines.append(
                    f"{service_id}: {field_name} changed from {before.get(field_name)} to {after.get(field_name)}."
                )

        if field_changes:
            changed.append({"service_id": service_id, "changes": field_changes})

    if not summary_lines:
        summary_lines.append("No config changes detected compared with the previous version.")

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "summary_lines": summary_lines,
    }


def summarize_diff(diff_payload: dict[str, Any]) -> str:
    return " ".join(diff_payload.get("summary_lines", []))
