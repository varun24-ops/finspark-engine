from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml


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


def simulate_one(
    service_id: str,
    provider: str,
    service_type: str,
    adapter_name: str,
    timeout_ms: int,
    mandatory: bool,
    should_fail: bool,
) -> dict[str, Any]:
    issues = []
    adapter_library = MOCK_RESPONSES.get(adapter_name, {})
    baseline_latency = int(adapter_library.get("latency_ms", max(120, int(timeout_ms * 0.6))))
    latency_ms = baseline_latency if not should_fail else int(baseline_latency * 1.05)
    time.sleep(min(latency_ms, 250) / 1000.0)

    if not adapter_library:
        return {
            "service_id": service_id,
            "provider": provider,
            "service_type": service_type,
            "adapter": adapter_name,
            "status": "fail",
            "latency_ms": latency_ms,
            "issues": [f"No mock response defined for {adapter_name}"],
            "response": {},
            "error_code": None,
            "mandatory": mandatory,
        }

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
        status = "fail" if mandatory else "warn"

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

        result = simulate_one(
            service_id=service_id,
            provider=provider,
            service_type=service_type,
            adapter_name=adapter_name,
            timeout_ms=timeout_ms,
            mandatory=mandatory,
            should_fail=adapter_name in fail_adapters,
        )
        results.append(result)

    return results


if __name__ == "__main__":
    config_file = "configs/acme_lending_adapters.yaml"
    print(run_simulation(config_file, fail_adapters={"cibil-bureau-adapter"}))
