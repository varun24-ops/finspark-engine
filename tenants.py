from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TENANTS_ROOT = Path("tenants")
TENANT_INDEX = TENANTS_ROOT / "index.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "tenant"


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _load_index() -> dict[str, Any]:
    TENANTS_ROOT.mkdir(parents=True, exist_ok=True)
    if not TENANT_INDEX.exists():
        return {"tenants": {}}
    return json.loads(TENANT_INDEX.read_text(encoding="utf-8"))


def _write_index(index: dict[str, Any]) -> None:
    TENANT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    TENANT_INDEX.write_text(
        json.dumps(index, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def ensure_tenant_workspace(tenant_id: str) -> dict[str, Path | str]:
    normalized_tenant = slugify(tenant_id)
    base_dir = TENANTS_ROOT / normalized_tenant
    configs_dir = base_dir / "configs"
    audit_dir = base_dir / "audit"

    configs_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    return {
        "tenant_id": normalized_tenant,
        "base_dir": base_dir,
        "configs_dir": configs_dir,
        "audit_dir": audit_dir,
        "current_config": configs_dir / "current.yaml",
        "audit_log": audit_dir / "runs.jsonl",
    }


def register_tenant(display_name: str, access_code: str) -> dict[str, Any]:
    if not display_name.strip():
        raise ValueError("Tenant name is required.")
    if not access_code.strip():
        raise ValueError("Access code is required.")

    tenant_id = slugify(display_name)
    index = _load_index()
    if tenant_id in index["tenants"]:
        raise ValueError("Tenant already exists. Log in instead.")

    record = {
        "tenant_id": tenant_id,
        "display_name": display_name.strip(),
        "access_code_hash": _hash_secret(access_code),
        "created_at": _utc_now(),
        "last_login_at": None,
    }
    index["tenants"][tenant_id] = record
    _write_index(index)
    ensure_tenant_workspace(tenant_id)
    return record


def authenticate_tenant(tenant_id: str, access_code: str) -> bool:
    index = _load_index()
    tenant = index["tenants"].get(slugify(tenant_id))
    if not tenant:
        return False

    is_valid = hmac.compare_digest(
        tenant["access_code_hash"],
        _hash_secret(access_code),
    )
    if is_valid:
        tenant["last_login_at"] = _utc_now()
        index["tenants"][tenant["tenant_id"]] = tenant
        _write_index(index)
        ensure_tenant_workspace(tenant_id)
    return is_valid


def list_tenants() -> list[dict[str, Any]]:
    index = _load_index()
    tenants = list(index["tenants"].values())
    tenants.sort(key=lambda item: item["display_name"].lower())
    return tenants


def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    index = _load_index()
    return index["tenants"].get(slugify(tenant_id))
