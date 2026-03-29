from pydantic import BaseModel
import os
import json
from dotenv import load_dotenv
from groq import Groq

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
- type: one of — credit_bureau, kyc, gst, bank_verify, fraud, payment, other
- provider: the specific company providing the service (e.g. "CIBIL", "Razorpay")
- mandatory: true if the document says required/must/mandatory, false if optional/preferred

Return ONLY a valid JSON object in this exact structure — no explanation, 
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
"""

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def parse_brd(text: str) -> ParsedBRD:
    print("fetching...")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    )
    output = response.choices[0].message.content

    start = output.find("{")
    end = output.rfind("}") + 1
    json_str = output[start:end]

    try:
        data = json.loads(json_str)
        return ParsedBRD(**data)
    except json.JSONDecodeError:
        print("Error: Model returned invalid JSON")
        print("Raw output:", output)
        raise

if __name__ == "__main__":
    sample = """
    Acme Lending requires CIBIL for credit checks (mandatory).
    UIDAI eKYC is mandatory for all borrowers.
    GST verification via NIC is optional.
    Razorpay penny drop is mandatory for bank validation.
    """
    result = parse_brd(sample)
    print(result.model_dump_json(indent=2))