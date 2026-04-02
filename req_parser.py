from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from errors import BRDParsingError
from registry import get_adapter

try:
    from groq import Groq
except ImportError:
    Groq = None


class ServiceRequirement(BaseModel):
    id: str
    name: str
    type: str
    provider: str
    mandatory: bool
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class ParsedBRD(BaseModel):
    tenant_id: str
    services: list[ServiceRequirement]
    parse_mode: str = "rules+evidence"
    parser_notes: list[str] = Field(default_factory=list)


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
- confidence: a number between 0 and 1 reflecting how explicit the requirement is
- evidence: short phrases summarizing the text that justified the extraction

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
      "mandatory": true,
      "confidence": 0.94,
      "evidence": [
        "Document explicitly requires CIBIL for bureau checks"
      ]
    }
  ]
}

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
client = Groq(api_key=_groq_api_key) if _groq_api_key and Groq is not None else None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "tenant"


def _split_sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


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
                rf"{primary_pattern}.*?(?:fallback|backup).+?{provider_pattern}",
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


def _find_primary_provider(sentence: str, fallback_provider: str) -> str | None:
    for provider, meta in PROVIDER_HINTS.items():
        if provider == fallback_provider:
            continue
        aliases = [provider.lower(), *meta["aliases"]]
        if any(alias in sentence.lower() for alias in aliases) and _provider_is_fallback_in_sentence(
            sentence,
            fallback_provider,
            provider,
        ):
            return provider
    return None


def _confidence_from_signals(
    *,
    alias_match: bool,
    mandatory: bool,
    typed: bool,
    fallback_only: bool,
    generic: bool,
) -> float:
    score = 0.35
    if alias_match:
        score += 0.28
    if typed:
        score += 0.14
    if mandatory:
        score += 0.08
    if generic:
        score -= 0.03
    if fallback_only:
        score -= 0.14
    return round(max(0.2, min(score, 0.98)), 2)


def _service_evidence(
    sentence: str,
    provider: str,
    service_type: str,
    mandatory: bool,
    fallback_only: bool,
    primary_provider: str | None = None,
) -> list[str]:
    evidence = [
        f"Detected {provider} for {service_type.replace('_', ' ')} in: {sentence.strip()}",
    ]
    if mandatory:
        evidence.append(f"Sentence marks {provider} as required or mandatory.")
    if fallback_only:
        if primary_provider:
            evidence.append(f"{provider} appears as fallback for {primary_provider}.")
        else:
            evidence.append(f"{provider} appears in fallback or alternate-provider language.")
    return evidence


def _upsert_service(
    services_by_provider: dict[str, ServiceRequirement],
    service: ServiceRequirement,
) -> None:
    existing = services_by_provider.get(service.provider.lower())
    if existing is None:
        services_by_provider[service.provider.lower()] = service
        return

    existing.mandatory = existing.mandatory or service.mandatory
    existing.confidence = max(existing.confidence, service.confidence)
    existing.evidence = _dedupe_strings(existing.evidence + service.evidence)


def _normalize_services(parsed: ParsedBRD, text: str) -> ParsedBRD:
    sentences = _split_sentences(text)
    services_by_provider = {service.provider.lower(): service for service in parsed.services}
    removed_providers: set[str] = set()
    parser_notes = list(parsed.parser_notes)

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

        service.mandatory = bool(
            service.mandatory
            or registry_entry.get("mandatory_default", False)
            or service.type == "credit_bureau"
        )
        service.confidence = round(min(0.99, max(service.confidence, backup_service.confidence, 0.84)), 2)
        service.evidence = _dedupe_strings(
            service.evidence
            + [
                f"{backup_service.provider} is modeled as fallback for {service.provider} based on BRD wording.",
            ]
        )
        removed_providers.add(backup_service.provider.lower())
        parser_notes.append(
            f"Collapsed fallback-only provider {backup_service.provider} under primary provider {service.provider}."
        )

    normalized_services = [
        service
        for service in parsed.services
        if service.provider.lower() not in removed_providers
    ]
    return ParsedBRD(
        tenant_id=parsed.tenant_id,
        services=normalized_services,
        parse_mode=parsed.parse_mode,
        parser_notes=_dedupe_strings(parser_notes),
    )


def _local_parse(text: str) -> ParsedBRD:
    if not text.strip():
        raise BRDParsingError("BRD text is empty.")

    services_by_provider: dict[str, ServiceRequirement] = {}
    sentences = _split_sentences(text)
    parser_notes = ["Local evidence-driven parser analyzed provider, fallback, and mandatory signals."]

    for sentence in sentences:
        lower_sentence = sentence.lower()
        matched_known_provider = False
        sentence_type = _infer_service_type(sentence)

        for provider, meta in PROVIDER_HINTS.items():
            if not any(alias in lower_sentence for alias in meta["aliases"]):
                continue

            matched_known_provider = True
            mandatory = _sentence_is_mandatory(sentence)
            primary_provider = _find_primary_provider(sentence, provider)
            fallback_only = primary_provider is not None or any(
                keyword in lower_sentence for keyword in FALLBACK_KEYWORDS
            )
            service = ServiceRequirement(
                id=meta["id"],
                name=meta["name"],
                type=meta["type"],
                provider=provider,
                mandatory=mandatory,
                confidence=_confidence_from_signals(
                    alias_match=True,
                    mandatory=mandatory,
                    typed=True,
                    fallback_only=fallback_only,
                    generic=False,
                ),
                evidence=_service_evidence(
                    sentence,
                    provider,
                    meta["type"],
                    mandatory,
                    fallback_only,
                    primary_provider,
                ),
            )
            _upsert_service(services_by_provider, service)

        if matched_known_provider:
            continue

        inferred_type = sentence_type
        inferred_provider = _infer_provider_name(sentence)
        if not inferred_type or not inferred_provider:
            continue

        mandatory = _sentence_is_mandatory(sentence)
        service = ServiceRequirement(
            id=_slugify(inferred_provider),
            name=f"{inferred_provider} {inferred_type.replace('_', ' ').title()}",
            type=inferred_type,
            provider=inferred_provider.strip(),
            mandatory=mandatory,
            confidence=_confidence_from_signals(
                alias_match=False,
                mandatory=mandatory,
                typed=True,
                fallback_only=False,
                generic=True,
            ),
            evidence=_service_evidence(
                sentence,
                inferred_provider.strip(),
                inferred_type,
                mandatory,
                False,
            ),
        )
        _upsert_service(services_by_provider, service)

    return ParsedBRD(
        tenant_id=_infer_tenant_id(text),
        services=list(services_by_provider.values()),
        parse_mode="rules+evidence",
        parser_notes=parser_notes,
    )


def _merge_with_local_insights(llm_parsed: ParsedBRD, local_parsed: ParsedBRD) -> ParsedBRD:
    merged_services = {service.provider.lower(): service for service in llm_parsed.services}

    for local_service in local_parsed.services:
        existing = merged_services.get(local_service.provider.lower())
        if existing is None:
            merged_services[local_service.provider.lower()] = local_service
            continue

        existing.mandatory = existing.mandatory or local_service.mandatory
        existing.confidence = round(max(existing.confidence or 0.0, local_service.confidence, 0.82), 2)
        existing.evidence = _dedupe_strings(existing.evidence + local_service.evidence)

    tenant_id = llm_parsed.tenant_id or local_parsed.tenant_id
    parser_notes = _dedupe_strings(
        list(local_parsed.parser_notes)
        + list(llm_parsed.parser_notes)
        + ["Merged LLM extraction with deterministic rule-based evidence."]
    )
    return ParsedBRD(
        tenant_id=tenant_id,
        services=list(merged_services.values()),
        parse_mode="groq+rules",
        parser_notes=parser_notes,
    )


def parse_brd(text: str) -> ParsedBRD:
    if not text.strip():
        raise BRDParsingError("BRD text is empty.")

    local_parsed = _normalize_services(_local_parse(text), text)
    if client is None:
        local_parsed.parser_notes = _dedupe_strings(
            local_parsed.parser_notes
            + ["Groq parser unavailable; using local evidence-driven extraction only."]
        )
        return local_parsed

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        output = response.choices[0].message.content or ""
        start = output.find("{")
        end = output.rfind("}") + 1
        json_str = output[start:end]
        if not json_str.strip():
            raise BRDParsingError("Groq parser did not return a JSON object.")

        data = json.loads(json_str)
        if not data.get("tenant_id"):
            data["tenant_id"] = local_parsed.tenant_id
        parsed = _normalize_services(ParsedBRD(**data), text)
        if not parsed.services:
            return local_parsed
        return _merge_with_local_insights(parsed, local_parsed)
    except Exception:
        local_parsed.parser_notes = _dedupe_strings(
            local_parsed.parser_notes
            + ["Groq parsing failed; fell back to local evidence-driven extraction."]
        )
        return local_parsed


if __name__ == "__main__":
    sample = """
    Acme Lending requires CIBIL for credit checks (mandatory) and uses Experian as fallback.
    UIDAI eKYC is mandatory for all borrowers.
    GST verification via NIC is optional.
    Razorpay penny drop is mandatory for bank validation.
    """
    result = parse_brd(sample)
    print(result.model_dump_json(indent=2))
