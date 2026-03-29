import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from parser import ParsedBRD

ADAPTER_REGISTRY = {
    # Credit Bureaus
    "CIBIL": {
        "adapter": "cibil-bureau-adapter",
        "version": "v3.1",
        "defaults": {"timeout": 3000}
    },
    "Experian": {
        "adapter": "experian-bureau-adapter",
        "version": "v2.9",
        "defaults": {"timeout": 3200}
    },

    # KYC
    "UIDAI": {
        "adapter": "uidai-ekyc-adapter",
        "version": "v2.4",
        "defaults": {"timeout": 2000}
    },

    # GST Verification
    "NIC": {
        "adapter": "nic-gst-adapter",
        "version": "v1.8",
        "defaults": {"timeout": 2500}
    },
    "GSTN": {
        "adapter": "gstn-verification-adapter",
        "version": "v1.2",
        "defaults": {"timeout": 2600}
    },

    # Bank / Payment Validation
    "Razorpay": {
        "adapter": "razorpay-penny-drop-adapter",
        "version": "v4.0",
        "defaults": {"timeout": 1500}
    },
    "PayU": {
        "adapter": "payu-payment-gateway-adapter",
        "version": "v5.3",
        "defaults": {"timeout": 1800}
    },
}

def fallback_rule(mandatory: bool) -> str:
    return "fail_closed" if mandatory else "skip"

def generate_config(parsed: ParsedBRD) -> str:
    enriched_services = []
    for svc in parsed.services:
        registry = ADAPTER_REGISTRY.get(svc.provider)
        if not registry:
            raise ValueError(f"No adapter registry entry for provider: {svc.provider}")
        enriched_services.append({
            "id": svc.id,
            "name": svc.name,
            "provider": svc.provider,
            "mandatory": svc.mandatory,
            "adapter": registry["adapter"],
            "version": registry["version"],
            "timeout": registry["defaults"]["timeout"],
            "fallback": fallback_rule(svc.mandatory),
            "vault_key": f"vault://{parsed.tenant_id}/{svc.id}/api_key"
        })

    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("integration_config.yaml.j2")
    rendered_yaml = template.render(
        tenant_id=parsed.tenant_id,
        services=enriched_services,
        generated_at=datetime.utcnow().isoformat()
    )

    os.makedirs("configs", exist_ok=True)
    output_path = f"configs/{parsed.tenant_id}_adapters.yaml"
    with open(output_path, "w") as f:
        f.write(rendered_yaml)
    return output_path

if __name__ == "__main__":
    from parser import parse_brd
    sample_brd = """
    Acme Lending requires CIBIL for credit checks (mandatory).
    UIDAI eKYC is mandatory for all borrowers.
    GST verification via NIC is optional.
    Razorpay penny drop is mandatory for bank validation.
    """
    parsed = parse_brd(sample_brd)
    path = generate_config(parsed)
    print(f"Config generated at: {path}")