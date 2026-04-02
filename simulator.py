from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from errors import SimulationEngineError
from policy_engine import PolicyEvaluation, evaluate_service_policy, normalize_backup_provider
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
        payload = config_source
    else:
        path = Path(config_source)
        if not path.exists():
            raise SimulationEngineError(f"Config not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

    integrations = payload.get("integrations")
    if not isinstance(integrations, dict):
        raise SimulationEngineError("Config must contain an `integrations` mapping.")
    return payload


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(results),
        "passed": sum(1 for result in results if result["status"] == "pass"),
        "failed": sum(1 for result in results if result["status"] == "fail"),
        "warnings": sum(1 for result in results if result["status"] == "warn"),
    }


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
    policy_evaluation: PolicyEvaluation | None = None,
) -> dict[str, Any]:
    policy_issues = list(policy_evaluation.issues if policy_evaluation else [])
    policy_advisories = list(policy_evaluation.advisories if policy_evaluation else [])
    technical_issues: list[str] = []

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
        technical_issues.append(f"Provider returned failure payload: {message}")

    for field_name in adapter_library.get("required_fields", []):
        if field_name not in response:
            technical_issues.append(f"Missing required field: {field_name}")

    if latency_ms > timeout_ms:
        technical_issues.append(f"Latency {latency_ms}ms exceeded timeout {timeout_ms}ms")

    policy_status = "fail" if policy_issues else "warn" if policy_advisories else "pass"
    technical_status = (
        "fail"
        if technical_issues and mandatory
        else "warn"
        if technical_issues
        else "pass"
    )

    if policy_issues or (technical_issues and mandatory):
        status = "fail"
    elif technical_issues or policy_advisories:
        status = "warn"
    else:
        status = "pass"

    issues = list(policy_issues) + list(technical_issues) + list(policy_advisories)

    return {
        "service_id": service_id,
        "provider": provider,
        "service_type": service_type,
        "adapter": adapter_name,
        "status": status,
        "latency_ms": latency_ms,
        "issues": issues,
        "technical_issues": technical_issues,
        "policy_issues": policy_issues,
        "policy_advisories": policy_advisories,
        "technical_status": technical_status,
        "policy_status": policy_status,
        "validation_mode": "technical+policy",
        "response": response,
        "error_code": response.get("errorCode"),
        "mandatory": mandatory,
    }


def _should_attempt_backup(
    technical_issues: list[str],
    fallback_mode: str,
    backup_provider: str | None,
    policy_breach: bool,
) -> bool:
    if policy_breach or fallback_mode != "use_backup" or not backup_provider:
        return False
    return bool(technical_issues)


def run_simulation(
    config_source: str | Path | dict[str, Any],
    fail_adapters: set[str] | None = None,
) -> list[dict[str, Any]]:
    fail_adapters = fail_adapters or set()
    config = _load_config(config_source)
    integrations = config.get("integrations", {})
    results = []

    for service_id, service_cfg in integrations.items():
        if not isinstance(service_cfg, dict):
            raise SimulationEngineError(f"Integration `{service_id}` must be a mapping.")

        adapter_value = str(service_cfg.get("adapter", ""))
        adapter_name = adapter_value.split("@", 1)[0]
        timeout_ms = int(service_cfg.get("timeout_ms", 500))
        mandatory = bool(service_cfg.get("mandatory", False))
        provider = str(service_cfg.get("provider", "Unknown"))
        service_type = str(service_cfg.get("service_type", "other"))
        fallback_mode = str(service_cfg.get("fallback", "")).strip()
        backup_provider = normalize_backup_provider(service_cfg.get("backup_provider"))
        policy_evaluation = evaluate_service_policy(service_id, service_cfg, integrations)

        result = simulate_one(
            service_id=service_id,
            provider=provider,
            service_type=service_type,
            adapter_name=adapter_name,
            timeout_ms=timeout_ms,
            mandatory=mandatory,
            should_fail=adapter_name in fail_adapters,
            policy_evaluation=policy_evaluation,
        )

        if _should_attempt_backup(
            result["technical_issues"],
            fallback_mode,
            backup_provider,
            policy_evaluation.critical,
        ):
            backup_entry = get_adapter(str(backup_provider))
            if backup_entry is None:
                message = f"Fallback provider {backup_provider} is not available in the registry."
                result["technical_issues"].append(message)
                result["issues"].append(message)
                result["technical_status"] = "fail" if mandatory else "warn"
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
                    result["status"] = (
                        "fail"
                        if result["policy_status"] == "fail"
                        else "warn"
                        if result["policy_status"] == "warn"
                        else "pass"
                    )
                    result["technical_status"] = "pass"
                    result["response"] = backup_result["response"]
                    result["error_code"] = None
                    fallback_message = (
                        f"Primary adapter {adapter_name} failed; fallback to "
                        f"{backup_entry['adapter']} succeeded."
                    )
                    result["technical_issues"] = [fallback_message]
                    result["issues"] = (
                        list(result["policy_issues"])
                        + [fallback_message]
                        + list(result["policy_advisories"])
                    )
                else:
                    result["technical_issues"].append(
                        f"Fallback provider {backup_entry['provider']} also failed."
                    )
                    result["technical_issues"].extend(
                        f"Fallback issue: {issue}" for issue in backup_result["issues"]
                    )
                    result["issues"] = (
                        list(result["policy_issues"])
                        + list(result["technical_issues"])
                        + list(result["policy_advisories"])
                    )
                    result["error_code"] = backup_result.get("error_code") or result.get(
                        "error_code"
                    )
                    result["technical_status"] = "fail" if mandatory else "warn"
                    result["status"] = "fail" if mandatory else "warn"

        results.append(result)

    return results


if __name__ == "__main__":
    config_file = "configs/acme_lending_adapters.yaml"
    print(run_simulation(config_file, fail_adapters={"cibil-bureau-adapter"}))
