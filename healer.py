from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from diff import diff_configs, summarize_diff
from errors import HealingError
from registry import find_backup_adapter, get_adapter
from simulator import run_simulation

try:
    from groq import Groq
except ImportError:
    Groq = None

load_dotenv()
_groq_api_key = os.getenv("GROQ_API_KEY")
_groq_client = Groq(api_key=_groq_api_key) if _groq_api_key and Groq is not None else None


def _load_config(path: str | Path) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HealingError(f"Could not read config for healing: {path}") from exc


def _write_config(path: str | Path, payload: dict[str, Any]) -> None:
    try:
        with Path(path).open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)
    except OSError as exc:
        raise HealingError(f"Could not write healed config: {path}") from exc


def _find_service_id(config_payload: dict[str, Any], adapter_name: str) -> str | None:
    for service_id, service_cfg in config_payload.get("integrations", {}).items():
        configured_adapter = str(service_cfg.get("adapter", "")).split("@", 1)[0]
        if configured_adapter == adapter_name:
            return service_id
    return None


def _heuristic_diagnosis(result: dict[str, Any], actions: list[str]) -> str:
    if actions:
        return " ".join(actions)
    if any("Policy breach" in issue for issue in result.get("issues", [])):
        return "Detected config drift against registry policy, but there was no safe auto-correction."
    if any("Latency" in issue for issue in result.get("issues", [])):
        return "Observed a timeout breach and no safe timeout patch was available."
    if result.get("error_code"):
        return f"Provider responded with {result['error_code']} and no fallback provider was configured."
    return "Simulation failed but there was no deterministic patch for this adapter."


def _ai_diagnosis(result: dict[str, Any], actions: list[str]) -> str | None:
    if _groq_client is None:
        return None

    prompt = {
        "simulation_result": result,
        "proposed_actions": actions,
    }
    try:
        response = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a fintech integration reliability engineer. "
                        "Summarize the root cause and the config fix in one short paragraph."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None


def _patch_service(
    tenant_id: str,
    service_id: str,
    service_cfg: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    issues = result.get("issues", [])
    registry_entry = get_adapter(str(service_cfg.get("provider", "")))

    if registry_entry:
        expected_adapter = f"{registry_entry['adapter']}@{registry_entry['version']}"
        expected_fallback = str(registry_entry.get("fallback_mode", "")).strip()
        expected_role = str(registry_entry.get("role", "primary"))
        expected_backup = registry_entry.get("backup_provider")
        expected_mandatory = bool(registry_entry.get("mandatory_default", False))
        expected_timeout = int(registry_entry.get("timeout_ms", service_cfg.get("timeout_ms", 1000)))

        if expected_mandatory and not bool(service_cfg.get("mandatory", False)):
            service_cfg["mandatory"] = True
            actions.append(f"{service_id}: restored mandatory flag from registry policy.")

        if expected_fallback and service_cfg.get("fallback") != expected_fallback:
            service_cfg["fallback"] = expected_fallback
            actions.append(
                f"{service_id}: reset fallback mode to registry-approved value `{expected_fallback}`."
            )

        if service_cfg.get("role") != expected_role:
            service_cfg["role"] = expected_role
            actions.append(f"{service_id}: restored role `{expected_role}` from registry policy.")

        if service_cfg.get("backup_provider") != expected_backup:
            service_cfg["backup_provider"] = expected_backup
            actions.append(
                f"{service_id}: restored backup provider `{expected_backup or 'none'}` from registry."
            )

        if service_cfg.get("adapter") != expected_adapter:
            service_cfg["adapter"] = expected_adapter
            actions.append(
                f"{service_id}: aligned adapter version to registry-approved `{expected_adapter}`."
            )

        if int(service_cfg.get("timeout_ms", 0)) < expected_timeout:
            old_timeout = int(service_cfg.get("timeout_ms", 0))
            service_cfg["timeout_ms"] = expected_timeout
            actions.append(
                f"{service_id}: raised timeout from {old_timeout}ms to registry minimum {expected_timeout}ms."
            )

    if any("Latency" in issue for issue in issues):
        old_timeout = int(service_cfg.get("timeout_ms", 1000))
        new_timeout = max(old_timeout + 500, int(old_timeout * 1.35))
        service_cfg["timeout_ms"] = new_timeout
        actions.append(
            f"{service_id}: increased timeout from {old_timeout}ms to {new_timeout}ms."
        )

    if not str(service_cfg.get("auth", "")).startswith("vault://"):
        service_cfg["auth"] = f"vault://{tenant_id}/{service_id}/api_key"
        actions.append(f"{service_id}: restored vault-backed credential reference.")

    if result.get("error_code") or any("failure payload" in issue.lower() for issue in issues):
        backup_provider = service_cfg.get("backup_provider")
        backup_adapter = get_adapter(str(backup_provider)) if backup_provider else None
        if backup_adapter is None:
            backup_adapter = find_backup_adapter(
                str(service_cfg.get("service_type", "")),
                str(service_cfg.get("provider", "")),
            )

        if backup_adapter and backup_adapter["provider"] != service_cfg.get("provider"):
            previous_provider = service_cfg.get("provider")
            service_cfg["provider"] = backup_adapter["provider"]
            service_cfg["backup_provider"] = previous_provider
            service_cfg["adapter"] = (
                f"{backup_adapter['adapter']}@{backup_adapter['version']}"
            )
            service_cfg["timeout_ms"] = max(
                int(service_cfg.get("timeout_ms", 1000)),
                int(backup_adapter["timeout_ms"]),
            )
            service_cfg["auth"] = f"vault://{tenant_id}/{service_id}/api_key"
            actions.append(
                f"{service_id}: switched provider from {previous_provider} to backup provider "
                f"{backup_adapter['provider']}."
            )

    registry_fallback = str(registry_entry.get("fallback_mode", "")).strip() if registry_entry else ""
    if (
        not result.get("mandatory", False)
        and service_cfg.get("fallback") != "skip"
        and registry_fallback in {"", "skip"}
    ):
        service_cfg["fallback"] = "skip"
        actions.append(f"{service_id}: relaxed fallback mode to skip for an optional integration.")

    return actions


def self_heal_config(
    config_path: str | Path,
    fail_adapters: set[str] | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    config_path = Path(config_path)
    config_payload = _load_config(config_path)
    tenant_id = str(config_payload.get("tenant_id", "tenant"))
    fail_adapters = fail_adapters or set()

    attempts: list[dict[str, Any]] = []
    try:
        results = run_simulation(config_payload, fail_adapters=fail_adapters)
    except Exception as exc:
        raise HealingError("Initial simulation failed during self-healing.") from exc

    for attempt_number in range(1, max_retries + 1):
        failures = [result for result in results if result["status"] == "fail"]
        if not failures:
            break

        before_patch = deepcopy(config_payload)
        attempt_actions: list[str] = []
        diagnoses: list[str] = []

        for result in failures:
            service_id = _find_service_id(config_payload, result["adapter"])
            if service_id is None:
                diagnoses.append(
                    f"{result['adapter']}: no matching integration block was found for healing."
                )
                continue

            service_cfg = config_payload["integrations"][service_id]
            actions = _patch_service(tenant_id, service_id, service_cfg, result)
            diagnoses.append(_ai_diagnosis(result, actions) or _heuristic_diagnosis(result, actions))
            attempt_actions.extend(actions)

        if not attempt_actions:
            break

        _write_config(config_path, config_payload)
        try:
            results = run_simulation(config_payload, fail_adapters=fail_adapters)
        except Exception as exc:
            raise HealingError("Simulation rerun failed during self-healing.") from exc
        diff_payload = diff_configs(before_patch, config_payload)
        attempts.append(
            {
                "attempt": attempt_number,
                "actions": attempt_actions,
                "diagnoses": diagnoses,
                "diff_summary": summarize_diff(diff_payload),
            }
        )

    final_yaml = config_path.read_text(encoding="utf-8")
    healed = all(result["status"] != "fail" for result in results)

    return {
        "results": results,
        "healed": healed,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "config_path": config_path,
        "config_yaml": final_yaml,
    }
