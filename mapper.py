from __future__ import annotations

import os
import re
from difflib import SequenceMatcher

_ENABLE_EMBEDDINGS = os.getenv("FINSPARK_USE_EMBEDDINGS", "").lower() in {
    "1",
    "true",
    "yes",
}

if _ENABLE_EMBEDDINGS:
    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity
    except Exception:
        SentenceTransformer = None
        cosine_similarity = None
else:
    SentenceTransformer = None
    cosine_similarity = None


CONFIDENCE_THRESHOLD = 0.80
_EMBEDDING_MODEL = None
_MODEL_LOAD_FAILED = False

FIELD_CONTEXT = {
    "pan_number": "PAN permanent account number tax identifier",
    "date_of_birth": "date of birth DOB age",
    "mobile_number": "mobile phone contact number",
    "amount_requested": "loan amount money requested rupees",
    "tenure_months": "loan tenure duration period months repayment",
    "product_type": "credit product loan type category",
    "panCard": "PAN permanent account number tax identifier",
    "dateOfBirth": "date of birth DOB age",
    "mobileNumber": "mobile phone contact number",
    "loanAmount": "loan amount money requested rupees",
    "tenureInMonths": "loan tenure duration period months repayment",
    "creditProductType": "credit product loan type category",
}


def enrich_field_name(field: str) -> str:
    parts = field.split(".")
    category = parts[0]
    field_part = parts[1]
    field_part = field_part.replace("_", " ")
    field_part = re.sub(r"([A-Z])", r" \1", field_part).lower()
    context = FIELD_CONTEXT.get(parts[1], "")
    return f"{field_part.strip()} {context} of the {category}".strip()


def _get_model():
    global _EMBEDDING_MODEL, _MODEL_LOAD_FAILED
    if SentenceTransformer is None:
        return None
    if _MODEL_LOAD_FAILED:
        return None
    if _EMBEDDING_MODEL is None:
        try:
            allow_download = os.getenv("FINSPARK_ALLOW_MODEL_DOWNLOAD", "").lower() in {
                "1",
                "true",
                "yes",
            }
            _EMBEDDING_MODEL = SentenceTransformer(
                "all-MiniLM-L6-v2",
                local_files_only=not allow_download,
            )
        except Exception:
            _MODEL_LOAD_FAILED = True
            return None
    return _EMBEDDING_MODEL


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left.lower(), right.lower()).ratio()
    return round((overlap * 0.6) + (sequence * 0.4), 4)


def map_fields(source: list[str], target: list[str]) -> list[dict]:
    results = []
    model = _get_model()

    if model is not None and cosine_similarity is not None:
        try:
            source_vecs = model.encode(source)
            target_vecs = model.encode(target)
            sim_matrix = cosine_similarity(source_vecs, target_vecs)
            for i, src in enumerate(source):
                best_idx = sim_matrix[i].argmax()
                best_score = float(sim_matrix[i][best_idx])
                best_target = target[best_idx]
                status = "mapped" if best_score >= CONFIDENCE_THRESHOLD else "review"
                results.append(
                    {
                        "source": src,
                        "target": best_target,
                        "confidence": round(best_score, 4),
                        "status": status,
                    }
                )
            return results
        except Exception:
            results = []

    for src in source:
        scores = [(_token_similarity(src, candidate), candidate) for candidate in target]
        best_score, best_target = max(scores, key=lambda item: item[0])
        status = "mapped" if best_score >= CONFIDENCE_THRESHOLD else "review"
        results.append(
            {
                "source": src,
                "target": best_target,
                "confidence": round(best_score, 4),
                "status": status,
            }
        )
    return results


if __name__ == "__main__":
    source_fields = [
        "borrower.pan_number",
        "borrower.date_of_birth",
        "borrower.mobile_number",
        "loan.amount_requested",
        "loan.tenure_months",
        "loan.product_type",
    ]
    cibil_target_fields = [
        "applicant.panCard",
        "applicant.dateOfBirth",
        "applicant.mobileNumber",
        "enquiry.loanAmount",
        "enquiry.tenureInMonths",
        "enquiry.creditProductType",
    ]

    source_fields_enriched = [enrich_field_name(value) for value in source_fields]
    target_fields_enriched = [enrich_field_name(value) for value in cibil_target_fields]
    mappings = map_fields(source_fields_enriched, target_fields_enriched)

    for index, mapping in enumerate(mappings):
        target_index = target_fields_enriched.index(mapping["target"])
        target_field = cibil_target_fields[target_index]
        flag = "" if mapping["status"] == "mapped" else "  <-- REVIEW"
        print(f"{source_fields[index]:<35} -> {target_field:<35} {mapping['confidence']}{flag}")
