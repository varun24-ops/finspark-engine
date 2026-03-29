from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import re

CONFIDENCE_THRESHOLD = 0.80

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
    field_part = re.sub(r'([A-Z])', r' \1', field_part).lower()
    context = FIELD_CONTEXT.get(parts[1], "")
    return f"{field_part.strip()} {context} of the {category}".strip()

def map_fields(source: list[str], target: list[str]) -> list[dict]:
    model = SentenceTransformer("all-MiniLM-L6-v2")
    source_vecs = model.encode(source)
    target_vecs = model.encode(target)
    sim_matrix = cosine_similarity(source_vecs, target_vecs)
    results = []
    for i, src in enumerate(source):
        best_idx = sim_matrix[i].argmax()
        best_score = float(sim_matrix[i][best_idx])
        best_target = target[best_idx]
        status = "mapped" if best_score >= CONFIDENCE_THRESHOLD else "review"
        results.append({
            "source": src,
            "target": best_target,
            "confidence": round(best_score, 4),
            "status": status
        })
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

    source_fields_enrich = [enrich_field_name(s) for s in source_fields]
    cibil_target_fields_enrich = [enrich_field_name(c) for c in cibil_target_fields]

    mappings = map_fields(source_fields_enrich, cibil_target_fields_enrich)

    for i, m in enumerate(mappings):
        original_src = source_fields[i]
        best_idx = cibil_target_fields_enrich.index(m['target'])
        original_tgt = cibil_target_fields[best_idx]
        flag = "" if m["status"] == "mapped" else "  <-- REVIEW"
        print(f"{original_src:<35} → {original_tgt:<35} {m['confidence']}{flag}")