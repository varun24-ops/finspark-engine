from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
REGISTRY_DB = DATA_DIR / "registry.db"

REGISTRY_POLICY_DEFAULTS = {
    "Razorpay": {
        "role": "primary",
        "mandatory_default": True,
        "fallback_mode": "fail_closed",
        "capabilities": ["account_validation", "name_match"],
    },
    "CIBIL": {
        "role": "primary",
        "mandatory_default": True,
        "fallback_mode": "use_backup",
        "backup_provider": "Experian",
    },
    "Experian": {
        "role": "fallback",
        "mandatory_default": False,
        "fallback_mode": "fail_closed",
        "backup_provider": None,
    },
    "UIDAI": {
        "role": "primary",
        "mandatory_default": True,
        "fallback_mode": "fail_closed",
    },
    "NIC": {
        "role": "primary",
        "mandatory_default": False,
        "fallback_mode": "use_backup",
        "backup_provider": "GSTN",
    },
    "GSTN": {
        "role": "fallback",
        "mandatory_default": False,
        "fallback_mode": "fail_closed",
        "backup_provider": None,
    },
    "PayU": {
        "role": "primary",
        "mandatory_default": True,
        "fallback_mode": "fail_closed",
    },
}

SEED_ADAPTERS = [
    {
        "provider": "CIBIL",
        "service_type": "credit_bureau",
        "adapter": "cibil-bureau-adapter",
        "version": "v3.1",
        "timeout_ms": 3000,
        "backup_provider": "Experian",
        "notes": "Primary bureau integration for retail lending.",
    },
    {
        "provider": "Experian",
        "service_type": "credit_bureau",
        "adapter": "experian-bureau-adapter",
        "version": "v2.9",
        "timeout_ms": 3200,
        "backup_provider": "CIBIL",
        "notes": "Fallback bureau adapter when CIBIL is unavailable.",
    },
    {
        "provider": "UIDAI",
        "service_type": "kyc",
        "adapter": "uidai-ekyc-adapter",
        "version": "v2.4",
        "timeout_ms": 2000,
        "backup_provider": None,
        "notes": "Aadhaar eKYC validation.",
    },
    {
        "provider": "NIC",
        "service_type": "gst",
        "adapter": "nic-gst-adapter",
        "version": "v1.8",
        "timeout_ms": 2500,
        "backup_provider": "GSTN",
        "notes": "Default GST verification provider.",
    },
    {
        "provider": "GSTN",
        "service_type": "gst",
        "adapter": "gstn-verification-adapter",
        "version": "v1.2",
        "timeout_ms": 2600,
        "backup_provider": "NIC",
        "notes": "Fallback GST verification provider.",
    },
    {
        "provider": "Razorpay",
        "service_type": "bank_verify",
        "adapter": "razorpay-penny-drop-adapter",
        "version": "v4.0",
        "timeout_ms": 1500,
        "backup_provider": None,
        "notes": "Bank account validation through penny drop.",
    },
    {
        "provider": "PayU",
        "service_type": "payment",
        "adapter": "payu-payment-gateway-adapter",
        "version": "v5.3",
        "timeout_ms": 1800,
        "backup_provider": None,
        "notes": "Collections and payment gateway flows.",
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path = REGISTRY_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    record["active"] = bool(record.pop("is_active"))
    return _decorate_record(record)


def _decorate_record(record: dict[str, Any]) -> dict[str, Any]:
    defaults = REGISTRY_POLICY_DEFAULTS.get(record["provider"], {})
    backup_provider = defaults.get("backup_provider", record.get("backup_provider"))
    mandatory_default = bool(
        defaults.get(
            "mandatory_default",
            record.get("service_type") in {"kyc", "bank_verify"},
        )
    )
    fallback_mode = str(
        defaults.get(
            "fallback_mode",
            "use_backup"
            if backup_provider
            else "fail_closed"
            if mandatory_default
            else "skip",
        )
    )
    record["backup_provider"] = backup_provider
    record["role"] = defaults.get("role", "primary")
    record["mandatory_default"] = mandatory_default
    record["fallback_mode"] = fallback_mode
    record["capabilities"] = list(defaults.get("capabilities", []))
    return record


def init_registry(db_path: Path = REGISTRY_DB) -> Path:
    with _connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS adapters (
                provider TEXT PRIMARY KEY,
                service_type TEXT NOT NULL,
                adapter TEXT NOT NULL,
                version TEXT NOT NULL,
                timeout_ms INTEGER NOT NULL,
                backup_provider TEXT,
                notes TEXT DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO adapters (
                provider,
                service_type,
                adapter,
                version,
                timeout_ms,
                backup_provider,
                notes,
                is_active,
                updated_at
            ) VALUES (
                :provider,
                :service_type,
                :adapter,
                :version,
                :timeout_ms,
                :backup_provider,
                :notes,
                1,
                :updated_at
            )
            """,
            [{**record, "updated_at": _utc_now()} for record in SEED_ADAPTERS],
        )
        connection.commit()
    return db_path


def list_adapters(include_inactive: bool = False) -> list[dict[str, Any]]:
    init_registry()
    query = """
        SELECT provider, service_type, adapter, version, timeout_ms,
               backup_provider, notes, is_active, updated_at
        FROM adapters
    """
    params: list[Any] = []
    if not include_inactive:
        query += " WHERE is_active = 1"
    query += " ORDER BY service_type, provider"

    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows if row is not None]


def get_adapter(provider: str) -> dict[str, Any] | None:
    init_registry()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT provider, service_type, adapter, version, timeout_ms,
                   backup_provider, notes, is_active, updated_at
            FROM adapters
            WHERE LOWER(provider) = LOWER(?) AND is_active = 1
            """,
            (provider,),
        ).fetchone()
    return _row_to_dict(row)


def registry_as_map() -> dict[str, dict[str, Any]]:
    return {record["provider"]: record for record in list_adapters()}


def upsert_adapter(
    provider: str,
    service_type: str,
    adapter: str,
    version: str,
    timeout_ms: int,
    backup_provider: str | None = None,
    notes: str = "",
    active: bool = True,
) -> dict[str, Any]:
    init_registry()
    provider = provider.strip()
    service_type = service_type.strip()
    adapter = adapter.strip()
    version = version.strip()

    if not provider:
        raise ValueError("Provider is required.")
    if not service_type:
        raise ValueError("Service type is required.")
    if not adapter:
        raise ValueError("Adapter name is required.")
    if not version:
        raise ValueError("Version is required.")
    if int(timeout_ms) <= 0:
        raise ValueError("Timeout must be greater than 0.")

    payload = {
        "provider": provider,
        "service_type": service_type,
        "adapter": adapter,
        "version": version,
        "timeout_ms": int(timeout_ms),
        "backup_provider": backup_provider.strip() if backup_provider else None,
        "notes": notes.strip(),
        "is_active": 1 if active else 0,
        "updated_at": _utc_now(),
    }
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO adapters (
                provider,
                service_type,
                adapter,
                version,
                timeout_ms,
                backup_provider,
                notes,
                is_active,
                updated_at
            ) VALUES (
                :provider,
                :service_type,
                :adapter,
                :version,
                :timeout_ms,
                :backup_provider,
                :notes,
                :is_active,
                :updated_at
            )
            ON CONFLICT(provider) DO UPDATE SET
                service_type = excluded.service_type,
                adapter = excluded.adapter,
                version = excluded.version,
                timeout_ms = excluded.timeout_ms,
                backup_provider = excluded.backup_provider,
                notes = excluded.notes,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            payload,
        )
        connection.commit()
    return get_adapter(provider) or payload


def delete_adapter(provider: str) -> None:
    init_registry()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE adapters
            SET is_active = 0, updated_at = ?
            WHERE LOWER(provider) = LOWER(?)
            """,
            (_utc_now(), provider),
        )
        connection.commit()


def find_backup_adapter(service_type: str, exclude_provider: str) -> dict[str, Any] | None:
    init_registry()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT provider, service_type, adapter, version, timeout_ms,
                   backup_provider, notes, is_active, updated_at
            FROM adapters
            WHERE service_type = ?
              AND LOWER(provider) != LOWER(?)
              AND is_active = 1
            ORDER BY provider
            LIMIT 1
            """,
            (service_type, exclude_provider),
        ).fetchone()
    return _row_to_dict(row)
