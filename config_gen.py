from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from diff import diff_configs, summarize_diff
from errors import ConfigGenerationError
from req_parser import ParsedBRD
from registry import get_adapter, init_registry
from tenants import ensure_tenant_workspace

TEMPLATE_NAME = "integration_config.yaml.j2"


@dataclass
class GeneratedConfig:
    tenant_id: str
    config_path: Path
    current_path: Path
    rendered_yaml: str
    version_label: str
    previous_path: Path | None = None
    previous_version_label: str | None = None
    version_history_count: int = 0
    generation_metadata: dict[str, object] | None = None
    diff_payload: dict | None = None
    diff_summary: str = "First config version generated for this tenant."


def fallback_rule(mandatory: bool, registry_entry: dict[str, object]) -> str:
    fallback_mode = str(registry_entry.get("fallback_mode", "")).strip()
    if fallback_mode:
        return fallback_mode
    if registry_entry.get("backup_provider"):
        return "use_backup"
    return "fail_closed" if mandatory else "skip"


def _build_enriched_services(parsed: ParsedBRD) -> list[dict[str, str | int | bool | None]]:
    enriched_services = []
    for svc in parsed.services:
        registry_entry = get_adapter(svc.provider)
        if not registry_entry:
            raise ConfigGenerationError(
                f"No adapter registry entry for provider: {svc.provider}"
            )

        mandatory = bool(svc.mandatory or registry_entry.get("mandatory_default", False))

        enriched_services.append(
            {
                "id": svc.id,
                "name": svc.name,
                "type": svc.type,
                "provider": registry_entry["provider"],
                "mandatory": mandatory,
                "adapter": registry_entry["adapter"],
                "version": registry_entry["version"],
                "available_versions": list(
                    registry_entry.get("available_versions", [registry_entry["version"]])
                ),
                "version_strategy": registry_entry.get("version_strategy", "fixed"),
                "timeout": registry_entry["timeout_ms"],
                "fallback": fallback_rule(mandatory, registry_entry),
                "backup_provider": registry_entry.get("backup_provider"),
                "role": registry_entry.get("role", "primary"),
                "vault_key": f"vault://{parsed.tenant_id}/{svc.id}/api_key",
            }
        )
    return enriched_services


def generate_config(parsed: ParsedBRD) -> GeneratedConfig:
    if not parsed.tenant_id.strip():
        raise ConfigGenerationError("Parsed BRD is missing a tenant identifier.")
    if not parsed.services:
        raise ConfigGenerationError("No parsed services are available to generate a config.")

    init_registry()
    workspace = ensure_tenant_workspace(parsed.tenant_id)
    configs_dir = workspace["configs_dir"]
    current_path = workspace["current_config"]
    assert isinstance(configs_dir, Path)
    assert isinstance(current_path, Path)

    try:
        previous_payload = (
            yaml.safe_load(current_path.read_text(encoding="utf-8"))
            if current_path.exists()
            else None
        )
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigGenerationError(
            f"Could not read the previous config version for tenant `{parsed.tenant_id}`."
        ) from exc

    previous_versions = sorted(configs_dir.glob("*_adapters.yaml"))
    previous_path = previous_versions[-1] if previous_versions else None
    previous_version_label = (
        str(previous_payload.get("version"))
        if isinstance(previous_payload, dict) and previous_payload.get("version")
        else None
    )
    enriched_services = _build_enriched_services(parsed)

    templates_dir = Path(__file__).resolve().parent / "templates"
    try:
        env = Environment(loader=FileSystemLoader(str(templates_dir)))
        template = env.get_template(TEMPLATE_NAME)
    except Exception as exc:
        raise ConfigGenerationError("Could not load the YAML config template.") from exc

    version_label = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    generation_metadata = {
        "parser_mode": parsed.parse_mode,
        "previous_config_version": previous_version_label,
        "version_history_count": len(previous_versions) + 1,
        "version_strategy": "latest_available",
    }
    rendered_yaml = template.render(
        tenant_id=parsed.tenant_id,
        config_version=version_label,
        services=enriched_services,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generation_metadata=generation_metadata,
    )

    versioned_path = configs_dir / f"{version_label}_adapters.yaml"
    try:
        versioned_path.write_text(rendered_yaml, encoding="utf-8")
        current_path.write_text(rendered_yaml, encoding="utf-8")
    except OSError as exc:
        raise ConfigGenerationError(
            f"Could not write generated configs for tenant `{parsed.tenant_id}`."
        ) from exc

    diff_payload = None
    diff_summary = "First config version generated for this tenant."
    if previous_payload:
        new_payload = yaml.safe_load(rendered_yaml) or {}
        diff_payload = diff_configs(previous_payload, new_payload)
        diff_summary = summarize_diff(diff_payload)

    return GeneratedConfig(
        tenant_id=parsed.tenant_id,
        config_path=versioned_path,
        current_path=current_path,
        rendered_yaml=rendered_yaml,
        version_label=version_label,
        previous_path=previous_path,
        previous_version_label=previous_version_label,
        version_history_count=len(previous_versions) + 1,
        generation_metadata=generation_metadata,
        diff_payload=diff_payload,
        diff_summary=diff_summary,
    )

if __name__ == "__main__":
    from parser import parse_brd

    sample_brd = """
    Acme Lending requires CIBIL for credit checks (mandatory).
    UIDAI eKYC is mandatory for all borrowers.
    GST verification via NIC is optional.
    Razorpay penny drop is mandatory for bank validation.
    """
    parsed = parse_brd(sample_brd)
    generated = generate_config(parsed)
    print(f"Config generated at: {generated.config_path}")
