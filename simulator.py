MOCK_RESPONSES = {
    "cibil-bureau-adapter": {
        "success": {
            "status": "SUCCESS",
            "creditScore": 742,
            "bureauReportId": "CBL-2024-9981234"
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "AUTH_401",
            "message": "Invalid API key"
        },
        "required_fields": ["status", "creditScore", "bureauReportId"]
    },

    "experian-bureau-adapter": {
        "success": {
            "status": "SUCCESS",
            "creditScore": 758,
            "reportId": "EXP-55667788",
            "riskBand": "LOW"
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "AUTH_403",
            "message": "Unauthorized access to Experian API"
        },
        "required_fields": ["status", "creditScore", "reportId"]
    },

    "uidai-ekyc-adapter": {
        "success": {
            "status": "SUCCESS",
            "aadhaarVerified": True,
            "kycId": "UIDAI-KYC-55667788",
            "nameMatchScore": 0.97
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "OTP_INVALID",
            "message": "OTP verification failed"
        },
        "required_fields": ["status", "aadhaarVerified", "kycId"]
    },

    "nic-gst-adapter": {
        "success": {
            "status": "SUCCESS",
            "gstin": "29ABCDE1234F1Z5",
            "legalName": "Acme Traders Pvt Ltd",
            "gstStatus": "ACTIVE"
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GST_NOT_FOUND",
            "message": "GSTIN does not exist"
        },
        "required_fields": ["status", "gstin", "gstStatus"]
    },

    "gstn-verification-adapter": {
        "success": {
            "status": "SUCCESS",
            "gstin": "27ABCDE4321F1Z2",
            "tradeName": "Global Supplies LLP",
            "registrationStatus": "ACTIVE"
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "GSTN_TIMEOUT",
            "message": "GSTN service timeout"
        },
        "required_fields": ["status", "gstin", "registrationStatus"]
    },

    "razorpay-penny-drop-adapter": {
        "success": {
            "status": "SUCCESS",
            "accountExists": True,
            "beneficiaryName": "Ravi Kumar",
            "transactionId": "RZP-99887766"
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "ACCOUNT_INVALID",
            "message": "Bank account not found"
        },
        "required_fields": ["status", "accountExists", "transactionId"]
    },

    "payu-payment-gateway-adapter": {
        "success": {
            "status": "SUCCESS",
            "paymentId": "PAYU-22334455",
            "amount": 12500.00,
            "currency": "INR",
            "paymentStatus": "CAPTURED"
        },
        "failure": {
            "status": "FAILURE",
            "errorCode": "PAYMENT_DECLINED",
            "message": "Transaction declined by issuer bank"
        },
        "required_fields": ["status", "paymentId", "paymentStatus"]
    }
}

import time
import random
def simulate_one(adapter_name, timeout_ms, mandatory, should_fail):
    issues = []
    
    latency_ms = random.randint(80, timeout_ms)
    time.sleep(latency_ms / 1000.0)
    
    adapter_lib = MOCK_RESPONSES.get(adapter_name, {})
    if not adapter_lib:
        return {
            "adapter": adapter_name,
            "status": "fail",
            "latency_ms": latency_ms,
            "issues": [f"No mock response defined for {adapter_name}"],
            "response": {}
        }
    response = adapter_lib["failure"] if should_fail else adapter_lib["success"]
    
    for field in adapter_lib.get("required_fields", []):
        if field not in response:
            issues.append(f"Missing required field: {field}")
    
    if latency_ms > timeout_ms:
        issues.append(
            f"Latency {latency_ms}ms exceeded timeout {timeout_ms}ms"
        )
    
    if not issues:
        status = "pass"
    else:
        status = "fail" if mandatory else "warn"
    
    return {
        "adapter": adapter_name,
        "status": status,
        "latency_ms": latency_ms,
        "issues": issues,
        "response": response
    }

import yaml

def run_simulation(config_path, fail_adapters=None):
    """
    fail_adapters: optional set of adapter base names to force failure
                   e.g. {"cibil-bureau-adapter"}
    """
    if fail_adapters is None:
        fail_adapters = set()

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    integrations = config.get("integrations", {})
    results = []

    print(f"\nRunning simulation for: {config_path}\n")

    for svc_id, svc_cfg in integrations.items():
        adapter_str = svc_cfg.get("adapter")          
        adapter_name = adapter_str.split("@")[0]      
        timeout_ms = int(svc_cfg.get("timeout_ms", 500))
        mandatory = bool(svc_cfg.get("mandatory", False))

        should_fail = adapter_name in fail_adapters

        result = simulate_one(
            adapter_name=adapter_name,
            timeout_ms=timeout_ms,
            mandatory=mandatory,
            should_fail=should_fail
        )

        results.append(result)

        print(
            f"{svc_id:<25} | "
            f"{adapter_name:<28} | "
            f"status={result['status']:<4} | "
            f"latency={result['latency_ms']}ms"
        )

    
    print("\nSummary:")
    for r in results:
        print(f"- {r['adapter']}: {r['status']}")

    return results




if __name__ == "__main__":
    config_file = "configs/acme_lending_adapters.yaml"

    print("\n=== Simulation: All Success ===")
    run_simulation(config_file, fail_adapters=set())

    print("\n=== Simulation: Force CIBIL Failure ===")
    run_simulation(config_file, fail_adapters={"cibil-bureau-adapter"})