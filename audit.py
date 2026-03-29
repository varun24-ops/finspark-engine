from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tenants import ensure_tenant_workspace


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_audit_entry(
    tenant_id: str,
    parsed_payload: dict[str, Any],
    simulation_results: list[dict[str, Any]],
    duration_ms: int,
    config_path: str | Path,
    healed: bool = False,
    healing_attempts: int = 0,
    diff_summary: str | None = None,
) -> dict[str, Any]:
    passed = sum(1 for result in simulation_results if result["status"] == "pass")
    failed = sum(1 for result in simulation_results if result["status"] == "fail")
    warned = sum(1 for result in simulation_results if result["status"] == "warn")

    return {
        "run_id": str(uuid.uuid4()),
        "timestamp": _utc_now(),
        "tenant_id": tenant_id,
        "config_path": str(config_path),
        "duration_ms": duration_ms,
        "healed": healed,
        "healing_attempts": healing_attempts,
        "diff_summary": diff_summary,
        "services_detected": [
            {
                "id": service["id"],
                "provider": service["provider"],
                "mandatory": service["mandatory"],
                "type": service["type"],
            }
            for service in parsed_payload.get("services", [])
        ],
        "simulation_summary": {
            "total": len(simulation_results),
            "passed": passed,
            "failed": failed,
            "warned": warned,
        },
        "simulation_results": simulation_results,
    }


def append_audit_log(entry: dict[str, Any]) -> Path:
    workspace = ensure_tenant_workspace(entry["tenant_id"])
    audit_path = workspace["audit_log"]
    assert isinstance(audit_path, Path)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return audit_path


def record_pipeline_run(
    tenant_id: str,
    parsed_payload: dict[str, Any],
    simulation_results: list[dict[str, Any]],
    duration_ms: int,
    config_path: str | Path,
    healed: bool = False,
    healing_attempts: int = 0,
    diff_summary: str | None = None,
) -> tuple[dict[str, Any], Path]:
    entry = build_audit_entry(
        tenant_id=tenant_id,
        parsed_payload=parsed_payload,
        simulation_results=simulation_results,
        duration_ms=duration_ms,
        config_path=config_path,
        healed=healed,
        healing_attempts=healing_attempts,
        diff_summary=diff_summary,
    )
    return entry, append_audit_log(entry)


def load_audit_entries(tenant_id: str, limit: int = 10) -> list[dict[str, Any]]:
    workspace = ensure_tenant_workspace(tenant_id)
    audit_path = workspace["audit_log"]
    assert isinstance(audit_path, Path)
    if not audit_path.exists():
        return []

    entries = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return list(reversed(entries[-limit:]))
