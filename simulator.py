from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml
from registry import get_adapter


MOCK_RESPONSES = {
    "cibil-bureau-adapter": {
        "success": {
            "status": "SUCCESS",
            "creditScore": 742,
            "bureauReportId": "CBL-2024-9981234",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "AUTH_401",
            "message": "Invalid API key",
        },
        "latency_ms": 1200,
        "required_fields": ["status", "creditScore", "bureauReportId"],
    },
    "experian-bureau-adapter": {
        "success": {
            "status": "SUCCESS",
            "creditScore": 758,
            "reportId": "EXP-55667788",
            "riskBand": "LOW",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "AUTH_403",
            "message": "Unauthorized access to Experian API",
        },
        "latency_ms": 1180,
        "required_fields": ["status", "creditScore", "reportId"],
    },
    "uidai-ekyc-adapter": {
        "success": {
            "status": "SUCCESS",
            "aadhaarVerified": True,
            "kycId": "UIDAI-KYC-55667788",
            "nameMatchScore": 0.97,
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "OTP_INVALID",
            "message": "OTP verification failed",
        },
        "latency_ms": 890,
        "required_fields": ["status", "aadhaarVerified", "kycId"],
    },
    "nic-gst-adapter": {
        "success": {
            "status": "SUCCESS",
            "gstin": "29ABCDE1234F1Z5",
            "legalName": "Acme Traders Pvt Ltd",
            "gstStatus": "ACTIVE",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GST_NOT_FOUND",
            "message": "GSTIN does not exist",
        },
        "latency_ms": 654,
        "required_fields": ["status", "gstin", "gstStatus"],
    },
    "gstn-verification-adapter": {
        "success": {
            "status": "SUCCESS",
            "gstin": "27ABCDE4321F1Z2",
            "tradeName": "Global Supplies LLP",
            "registrationStatus": "ACTIVE",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GSTN_TIMEOUT",
            "message": "GSTN service timeout",
        },
        "latency_ms": 780,
        "required_fields": ["status", "gstin", "registrationStatus"],
    },
    "razorpay-penny-drop-adapter": {
        "success": {
            "status": "SUCCESS",
            "accountExists": True,
            "beneficiaryName": "Ravi Kumar",
            "transactionId": "RZP-99887766",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "ACCOUNT_INVALID",
            "message": "Bank account not found",
        },
        "latency_ms": 445,
        "required_fields": ["status", "accountExists", "transactionId"],
    },
    "payu-payment-gateway-adapter": {
        "success": {
            "status": "SUCCESS",
            "paymentId": "PAYU-22334455",
            "amount": 12500.00,
            "currency": "INR",
            "paymentStatus": "CAPTURED",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "PAYMENT_DECLINED",
            "message": "Transaction declined by issuer bank",
        },
        "latency_ms": 990,
        "required_fields": ["status", "paymentId", "paymentStatus"],
    },
}

GENERIC_SERVICE_MOCKS = {
    "credit_bureau": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-BUREAU-1001",
            "creditScore": 735,
            "decision": "CLEAR",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_BUREAU_500",
            "message": "Dynamic bureau adapter simulation failed",
        },
        "latency_ms": 1600,
        "required_fields": ["status", "referenceId", "creditScore"],
    },
    "kyc": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-KYC-1001",
            "verified": True,
            "matchScore": 0.96,
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_KYC_500",
            "message": "Dynamic KYC adapter simulation failed",
        },
        "latency_ms": 900,
        "required_fields": ["status", "referenceId", "verified"],
    },
    "gst": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-GST-1001",
            "gstStatus": "ACTIVE",
            "gstin": "29ABCDE1234F1Z5",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_GST_500",
            "message": "Dynamic GST adapter simulation failed",
        },
        "latency_ms": 780,
        "required_fields": ["status", "referenceId", "gstStatus"],
    },
    "bank_verify": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-BANK-1001",
            "accountVerified": True,
            "beneficiaryName": "Demo Beneficiary",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_BANK_500",
            "message": "Dynamic bank verification adapter simulation failed",
        },
        "latency_ms": 500,
        "required_fields": ["status", "referenceId", "accountVerified"],
    },
    "payment": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-PAY-1001",
            "paymentStatus": "CAPTURED",
            "amount": 12500.0,
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_PAY_500",
            "message": "Dynamic payment adapter simulation failed",
        },
        "latency_ms": 950,
        "required_fields": ["status", "referenceId", "paymentStatus"],
    },
    "fraud": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-FRAUD-1001",
            "riskScore": 0.12,
            "decision": "APPROVE",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_FRAUD_500",
            "message": "Dynamic fraud adapter simulation failed",
        },
        "latency_ms": 1100,
        "required_fields": ["status", "referenceId", "decision"],
    },
    "other": {
        "success": {
            "status": "SUCCESS",
            "referenceId": "GEN-OTHER-1001",
            "adapterStatus": "READY",
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GEN_OTHER_500",
            "message": "Dynamic adapter simulation failed",
        },
        "latency_ms": 1000,
        "required_fields": ["status", "referenceId", "adapterStatus"],
    },
}


def _load_config(config_source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(config_source, dict):
        return config_source

    with Path(config_source).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(results),
        "passed": sum(1 for result in results if result["status"] == "pass"),
        "failed": sum(1 for result in results if result["status"] == "fail"),
        "warnings": sum(1 for result in results if result["status"] == "warn"),
    }


def _normalize_backup_provider(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return normalized


def _policy_issues(
    service_id: str,
    service_cfg: dict[str, Any],
    integrations: dict[str, Any],
) -> tuple[list[str], bool]:
    issues: list[str] = []
    critical = False

    service_type = str(service_cfg.get("service_type", "other"))
    provider = str(service_cfg.get("provider", "Unknown"))
    mandatory = bool(service_cfg.get("mandatory", False))
    fallback = str(service_cfg.get("fallback", "")).strip()
    backup_provider = _normalize_backup_provider(service_cfg.get("backup_provider"))
    registry_entry = get_adapter(provider)

    if registry_entry is None:
        issues.append(f"Policy breach: provider {provider} is not present in the adapter registry.")
        return issues, True

    expected_mandatory = bool(registry_entry.get("mandatory_default", False))
    expected_fallback = str(registry_entry.get("fallback_mode", "")).strip()
    expected_role = str(registry_entry.get("role", "primary")).strip()
    expected_backup_provider = _normalize_backup_provider(registry_entry.get("backup_provider"))

    if expected_mandatory and not mandatory:
        issues.append(
            f"Policy breach: registry marks {provider} as mandatory and runtime config cannot downgrade it."
        )
        critical = True

    if expected_fallback and fallback != expected_fallback:
        issues.append(
            f"Policy breach: registry requires fallback mode `{expected_fallback}` for {provider}, "
            f"but config uses `{fallback or 'none'}`."
        )
        critical = True

    if expected_backup_provider != backup_provider:
        issues.append(
            f"Policy breach: registry expects backup provider `{expected_backup_provider or 'none'}` "
            f"for {provider}, but config uses `{backup_provider or 'none'}`."
        )
        critical = True

    if fallback == "use_backup" and not backup_provider:
        issues.append("Policy breach: use_backup fallback requires a configured backup provider.")
        critical = True

    if service_type == "kyc" and not mandatory:
        issues.append("Policy breach: KYC must remain mandatory.")
        critical = True

    if service_type == "bank_verify" and not mandatory:
        issues.append("Policy breach: bank verification must remain mandatory.")
        critical = True

    referenced_as_backup = any(
        other_id != service_id
        and str(other_cfg.get("service_type", "other")) == service_type
        and _normalize_backup_provider(other_cfg.get("backup_provider")) == provider
        for other_id, other_cfg in integrations.items()
    )
    if expected_role == "fallback" and not referenced_as_backup:
        issues.append(
            f"Policy breach: {provider} is configured as a standalone {service_type} "
            "integration even though it is already modeled as another provider's fallback."
        )
        critical = True

    if service_type == "credit_bureau" and not mandatory:
        issues.append("Policy breach: credit bureau checks must be mandatory before loan decisioning.")
        critical = True

    return issues, critical


def _generic_mock_for(service_type: str, adapter_name: str, provider: str) -> dict[str, Any]:
    template = GENERIC_SERVICE_MOCKS.get(service_type, GENERIC_SERVICE_MOCKS["other"])
    mock = {
        "success": dict(template["success"]),
        "failure": dict(template["failure"]),
        "latency_ms": template["latency_ms"],
        "required_fields": list(template["required_fields"]),
    }
    mock["success"]["adapter"] = adapter_name
    mock["success"]["provider"] = provider
    mock["failure"]["adapter"] = adapter_name
    mock["failure"]["provider"] = provider
    return mock


def simulate_one(
    service_id: str,
    provider: str,
    service_type: str,
    adapter_name: str,
    timeout_ms: int,
    mandatory: bool,
    should_fail: bool,
    policy_issues: list[str] | None = None,
    policy_breach: bool = False,
) -> dict[str, Any]:
    issues = list(policy_issues or [])
    adapter_library = MOCK_RESPONSES.get(adapter_name) or _generic_mock_for(
        service_type,
        adapter_name,
        provider,
    )
    baseline_latency = int(adapter_library.get("latency_ms", max(120, int(timeout_ms * 0.6))))
    latency_ms = baseline_latency if not should_fail else int(baseline_latency * 1.05)
    time.sleep(min(latency_ms, 250) / 1000.0)

    response = adapter_library["failure"] if should_fail else adapter_library["success"]

    if response.get("status") != "SUCCESS":
        message = response.get("message") or response.get("errorCode") or "Unknown provider error"
        issues.append(f"Provider returned failure payload: {message}")

    for field_name in adapter_library.get("required_fields", []):
        if field_name not in response:
            issues.append(f"Missing required field: {field_name}")

    if latency_ms > timeout_ms:
        issues.append(f"Latency {latency_ms}ms exceeded timeout {timeout_ms}ms")

    if not issues:
        status = "pass"
    else:
        status = "fail" if mandatory or policy_breach else "warn"

    return {
        "service_id": service_id,
        "provider": provider,
        "service_type": service_type,
        "adapter": adapter_name,
        "status": status,
        "latency_ms": latency_ms,
        "issues": issues,
        "response": response,
        "error_code": response.get("errorCode"),
        "mandatory": mandatory,
    }


def _should_attempt_backup(
    result: dict[str, Any],
    fallback_mode: str,
    backup_provider: str | None,
    policy_breach: bool,
) -> bool:
    if policy_breach or fallback_mode != "use_backup" or not backup_provider:
        return False
    return bool(result["issues"])


def run_simulation(
    config_source: str | Path | dict[str, Any],
    fail_adapters: set[str] | None = None,
) -> list[dict[str, Any]]:
    if fail_adapters is None:
        fail_adapters = set()

    config = _load_config(config_source)
    integrations = config.get("integrations", {})
    results = []

    for service_id, service_cfg in integrations.items():
        adapter_value = str(service_cfg.get("adapter", ""))
        adapter_name = adapter_value.split("@", 1)[0]
        timeout_ms = int(service_cfg.get("timeout_ms", 500))
        mandatory = bool(service_cfg.get("mandatory", False))
        provider = str(service_cfg.get("provider", "Unknown"))
        service_type = str(service_cfg.get("service_type", "other"))
        fallback_mode = str(service_cfg.get("fallback", "")).strip()
        backup_provider = _normalize_backup_provider(service_cfg.get("backup_provider"))
        policy_issues, policy_breach = _policy_issues(service_id, service_cfg, integrations)

        result = simulate_one(
            service_id=service_id,
            provider=provider,
            service_type=service_type,
            adapter_name=adapter_name,
            timeout_ms=timeout_ms,
            mandatory=mandatory,
            should_fail=adapter_name in fail_adapters,
            policy_issues=policy_issues,
            policy_breach=policy_breach,
        )

        if _should_attempt_backup(result, fallback_mode, backup_provider, policy_breach):
            backup_entry = get_adapter(str(backup_provider))
            if backup_entry is None:
                result["issues"].append(
                    f"Fallback provider {backup_provider} is not available in the registry."
                )
                result["status"] = "fail" if mandatory else "warn"
            else:
                backup_result = simulate_one(
                    service_id=service_id,
                    provider=backup_entry["provider"],
                    service_type=service_type,
                    adapter_name=str(backup_entry["adapter"]),
                    timeout_ms=max(timeout_ms, int(backup_entry["timeout_ms"])),
                    mandatory=mandatory,
                    should_fail=str(backup_entry["adapter"]) in fail_adapters,
                )
                result["fallback_attempted"] = True
                result["fallback_provider"] = backup_entry["provider"]
                result["fallback_adapter"] = backup_entry["adapter"]
                result["fallback_result"] = backup_result
                result["latency_ms"] += backup_result["latency_ms"]

                if backup_result["status"] == "pass":
                    result["status"] = "pass"
                    result["response"] = backup_result["response"]
                    result["error_code"] = None
                    result["issues"] = [
                        f"Primary adapter {adapter_name} failed; fallback to "
                        f"{backup_entry['adapter']} succeeded."
                    ]
                else:
                    result["issues"].append(
                        f"Fallback provider {backup_entry['provider']} also failed."
                    )
                    result["issues"].extend(
                        f"Fallback issue: {issue}" for issue in backup_result["issues"]
                    )
                    result["error_code"] = backup_result.get("error_code") or result.get(
                        "error_code"
                    )
                    result["status"] = "fail" if mandatory else "warn"

        results.append(result)

    return results


if __name__ == "__main__":
    config_file = "configs/acme_lending_adapters.yaml"
    print(run_simulation(config_file, fail_adapters={"cibil-bureau-adapter"}))
