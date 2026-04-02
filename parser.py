from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel
from registry import get_adapter


class ServiceRequirement(BaseModel):
    id: str
    name: str
    type: str
    provider: str
    mandatory: bool


class ParsedBRD(BaseModel):
    tenant_id: str
    services: list[ServiceRequirement]


SYSTEM_PROMPT = """
You are an enterprise integration analyst specializing in reading
banking and fintech requirement documents.

Your job is to extract all external service integrations mentioned
in the document provided.

For each service found, identify:
- id: a short snake_case slug (e.g. "cibil", "uidai_ekyc")
- name: human readable name
- type: one of credit_bureau, kyc, gst, bank_verify, fraud, payment, other
- provider: the specific company providing the service (e.g. "CIBIL", "Razorpay")
- mandatory: true if the document says required/must/mandatory, false if optional/preferred

Return ONLY a valid JSON object in this exact structure, no explanation,
no markdown, no code blocks:

{
  "tenant_id": "slug-of-company-name-from-document",
  "services": [
    {
      "id": "cibil",
      "name": "CIBIL Bureau Check",
      "type": "credit_bureau",
      "provider": "CIBIL",
      "mandatory": true
    }
  ]
}

If something is ambiguous, make your best judgment. Never return anything outside the JSON object.
If a provider is only mentioned as a fallback, backup, or alternate provider for the same
integration, do not emit it as a separate standalone service.
"""


PROVIDER_HINTS = {
    "CIBIL": {
        "aliases": ["cibil", "transunion cibil"],
        "id": "cibil",
        "name": "CIBIL Bureau Check",
        "type": "credit_bureau",
    },
    "Experian": {
        "aliases": ["experian"],
        "id": "experian",
        "name": "Experian Bureau Check",
        "type": "credit_bureau",
    },
    "UIDAI": {
        "aliases": ["uidai", "aadhaar ekyc", "aadhaar e-kyc", "ekyc"],
        "id": "uidai_ekyc",
        "name": "UIDAI Aadhaar eKYC",
        "type": "kyc",
    },
    "NIC": {
        "aliases": ["nic", "gst via nic", "nic portal"],
        "id": "gst_nic",
        "name": "NIC GST Verification",
        "type": "gst",
    },
    "GSTN": {
        "aliases": ["gstn"],
        "id": "gst_gstn",
        "name": "GSTN Verification",
        "type": "gst",
    },
    "Razorpay": {
        "aliases": ["razorpay", "penny drop"],
        "id": "razorpay_penny_drop",
        "name": "Razorpay Penny Drop",
        "type": "bank_verify",
    },
    "PayU": {
        "aliases": ["payu", "payment gateway"],
        "id": "payu_gateway",
        "name": "PayU Payment Gateway",
        "type": "payment",
    },
}

MANDATORY_KEYWORDS = ("mandatory", "must", "required", "requires", "needs", "required for")
OPTIONAL_KEYWORDS = ("optional", "preferred", "nice to have", "can use", "may use")
FALLBACK_KEYWORDS = (
    "fallback",
    "backup",
    "secondary",
    "alternate",
    "alternative",
    "if unavailable",
    "if it fails",
    "if this fails",
)
GENERIC_TYPE_HINTS = {
    "credit_bureau": ("credit bureau", "bureau", "credit check", "credit checks"),
    "kyc": ("ekyc", "e-kyc", "kyc", "aadhaar"),
    "gst": ("gst", "gst verification", "gstin"),
    "bank_verify": ("penny drop", "bank validation", "bank verification", "account validation"),
    "payment": ("payment gateway", "collections", "payment"),
    "fraud": ("fraud", "fraud engine", "risk engine"),
}

load_dotenv()
_groq_api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=_groq_api_key) if _groq_api_key else None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "tenant"


def _infer_tenant_id(text: str) -> str:
    patterns = [
        r"([A-Z][A-Za-z0-9& ]+?)\s+(?:requires|needs|wants|plans)",
        r"for\s+([A-Z][A-Za-z0-9& ]+?)\s+(?:borrowers|customers|lending)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _slugify(match.group(1))
    return "demo_tenant"


def _sentence_is_mandatory(sentence: str) -> bool:
    lower = sentence.lower()
    if any(keyword in lower for keyword in OPTIONAL_KEYWORDS):
        return False
    return any(keyword in lower for keyword in MANDATORY_KEYWORDS)


def _provider_is_fallback_in_sentence(
    sentence: str,
    provider: str,
    primary_provider: str | None = None,
) -> bool:
    lower = sentence.lower()
    provider_pattern = re.escape(provider.lower())
    base_patterns = [
        rf"{provider_pattern}\s+(?:as\s+)?(?:fallback|backup|secondary|alternate|alternative)",
        rf"(?:fallback|backup|secondary|alternate|alternative)(?:\s+provider)?(?:\s+is|\s+to|:)?\s*{provider_pattern}",
    ]
    if primary_provider:
        primary_pattern = re.escape(primary_provider.lower())
        base_patterns.extend(
            [
                rf"if\s+{primary_pattern}.*?(?:fail|fails|unavailable).*?(?:use|switch to)\s+{provider_pattern}",
                rf"(?:use|switch to)\s+{provider_pattern}.*?if\s+{primary_pattern}.*?(?:fail|fails|unavailable)",
            ]
        )

    return any(re.search(pattern, lower) for pattern in base_patterns)


def _infer_service_type(sentence: str) -> str | None:
    lower = sentence.lower()
    for service_type, keywords in GENERIC_TYPE_HINTS.items():
        if any(keyword in lower for keyword in keywords):
            return service_type
    return None


def _infer_provider_name(sentence: str) -> str | None:
    patterns = [
        r"(?:requires|needs)\s+([A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&-]+)*)\s+for",
        r"via\s+([A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&-]+)*)",
        r"through\s+([A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&-]+)*)",
        r"using\s+([A-Z][A-Za-z0-9&-]*(?:\s+[A-Z][A-Za-z0-9&-]+)*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, sentence)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return None


def _normalize_services(parsed: ParsedBRD, text: str) -> ParsedBRD:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]
    services_by_provider = {service.provider.lower(): service for service in parsed.services}
    removed_providers: set[str] = set()

    for service in parsed.services:
        registry_entry = get_adapter(service.provider)
        if not registry_entry:
            continue

        backup_provider = registry_entry.get("backup_provider")
        if not backup_provider:
            continue

        backup_service = services_by_provider.get(str(backup_provider).lower())
        if backup_service is None or backup_service.type != service.type:
            continue

        is_fallback_provider = any(
            _provider_is_fallback_in_sentence(sentence, backup_service.provider, service.provider)
            for sentence in sentences
            if backup_service.provider.lower() in sentence.lower()
        )
        if not is_fallback_provider:
            continue

        if service.type == "credit_bureau":
            service.mandatory = True
        else:
            service.mandatory = service.mandatory or backup_service.mandatory
        removed_providers.add(backup_service.provider.lower())

    normalized_services = [
        service
        for service in parsed.services
        if service.provider.lower() not in removed_providers
    ]
    return ParsedBRD(tenant_id=parsed.tenant_id, services=normalized_services)


def _local_parse(text: str) -> ParsedBRD:
    services_by_provider: dict[str, ServiceRequirement] = {}
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]

    for sentence in sentences:
        lower_sentence = sentence.lower()
        matched_known_provider = False
        for provider, meta in PROVIDER_HINTS.items():
            if not any(alias in lower_sentence for alias in meta["aliases"]):
                continue

            matched_known_provider = True
            mandatory = _sentence_is_mandatory(sentence)
            existing = services_by_provider.get(provider)
            if existing:
                existing.mandatory = existing.mandatory or mandatory
                continue

            services_by_provider[provider] = ServiceRequirement(
                id=meta["id"],
                name=meta["name"],
                type=meta["type"],
                provider=provider,
                mandatory=mandatory,
            )

        if matched_known_provider:
            continue

        inferred_type = _infer_service_type(sentence)
        inferred_provider = _infer_provider_name(sentence)
        if not inferred_type or not inferred_provider:
            continue

        provider_key = inferred_provider.strip()
        mandatory = _sentence_is_mandatory(sentence)
        existing = services_by_provider.get(provider_key)
        if existing:
            existing.mandatory = existing.mandatory or mandatory
            continue

        services_by_provider[provider_key] = ServiceRequirement(
            id=_slugify(provider_key),
            name=f"{provider_key} {inferred_type.replace('_', ' ').title()}",
            type=inferred_type,
            provider=provider_key,
            mandatory=mandatory,
        )

    return ParsedBRD(
        tenant_id=_infer_tenant_id(text),
        services=list(services_by_provider.values()),
    )


def parse_brd(text: str) -> ParsedBRD:
    if client is None:
        return _normalize_services(_local_parse(text), text)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        output = response.choices[0].message.content
        start = output.find("{")
        end = output.rfind("}") + 1
        json_str = output[start:end]

        data = json.loads(json_str)
        if not data.get("tenant_id"):
            data["tenant_id"] = _infer_tenant_id(text)
        return _normalize_services(ParsedBRD(**data), text)
    except Exception:
        return _normalize_services(_local_parse(text), text)


if __name__ == "__main__":
    sample = """
    Acme Lending requires CIBIL for credit checks (mandatory).
    UIDAI eKYC is mandatory for all borrowers.
    GST verification via NIC is optional.
    Razorpay penny drop is mandatory for bank validation.
    """
    result = parse_brd(sample)
    print(result.model_dump_json(indent=2))
