import streamlit as st
from parser import parse_brd
from mapper import map_fields, enrich_field_name, FIELD_CONTEXT
from config_gen import generate_config, ADAPTER_REGISTRY
from simulator import run_simulation, MOCK_RESPONSES

st.set_page_config(
    page_title="FinSpark Integration Engine",
    page_icon="",
    layout="wide"
)

st.title("FinSpark — AI Integration Orchestration Engine")
st.caption("Transform requirement documents into production-ready integration configs")

st.divider()

# ─── Sidebar ───────────────────────────────────────────
with st.sidebar:
    st.subheader("Pipeline controls")
    sample_brd = """Acme Lending requires CIBIL for credit bureau checks (mandatory). UIDAI Aadhaar eKYC is mandatory for all borrowers. GST verification via NIC portal is optional for MSME loans. Razorpay penny drop is mandatory for bank account validation."""
    force_fail = st.multiselect(
        "Force adapter failure (for demo)",
        options=list(MOCK_RESPONSES.keys()),
        default=[]
    )
    st.divider()
    st.caption("Adapter registry")
    for provider, meta in ADAPTER_REGISTRY.items():
        st.code(f"{provider}: {meta['adapter']}@{meta['version']}", language=None)

# ─── Main input ────────────────────────────────────────
st.subheader("Step 1 — Paste your BRD")
brd_input = st.text_area(
    label="Requirement document",
    value=sample_brd,
    height=160,
    placeholder="Paste your BRD or SOW text here..."
)

run_btn = st.button("Run pipeline", type="primary", use_container_width=True)

if run_btn:
    if not brd_input.strip():
        st.error("Please paste a BRD before running.")
        st.stop()

    # ─── Stage 1: Parse ────────────────────────────────
    st.divider()
    st.subheader("Step 2 — Parsed requirements")

    with st.spinner("Parsing BRD with Llama 3.3..."):
        parsed = parse_brd(brd_input)

    col1, col2, col3 = st.columns(3)
    col1.metric("Tenant", parsed.tenant_id)
    col2.metric("Services found", len(parsed.services))
    col3.metric("Mandatory", sum(1 for s in parsed.services if s.mandatory))

    for svc in parsed.services:
        badge = "mandatory" if svc.mandatory else "optional"
        color = "red" if svc.mandatory else "gray"
        st.markdown(
            f"**{svc.name}** &nbsp; `{svc.type}` &nbsp; `{svc.provider}` &nbsp;"
            f":{color}[{badge}]"
        )

    with st.expander("View raw JSON"):
        st.json(parsed.model_dump())

    # ─── Stage 2: Field mapping ─────────────────────────
    st.divider()
    st.subheader("Step 3 — Field mappings (CIBIL adapter)")

    SOURCE_FIELDS = [
        "borrower.pan_number",
        "borrower.date_of_birth",
        "borrower.mobile_number",
        "loan.amount_requested",
        "loan.tenure_months",
        "loan.product_type",
    ]
    CIBIL_TARGET_FIELDS = [
        "applicant.panCard",
        "applicant.dateOfBirth",
        "applicant.mobileNumber",
        "enquiry.loanAmount",
        "enquiry.tenureInMonths",
        "enquiry.creditProductType",
    ]

    with st.spinner("Running semantic field mapping..."):
        enriched_src = [enrich_field_name(s) for s in SOURCE_FIELDS]
        enriched_tgt = [enrich_field_name(t) for t in CIBIL_TARGET_FIELDS]
        mappings = map_fields(enriched_src, enriched_tgt)

    for i, m in enumerate(mappings):
        original_src = SOURCE_FIELDS[i]
        best_idx = enriched_tgt.index(m['target'])
        original_tgt = CIBIL_TARGET_FIELDS[best_idx]
        conf = m['confidence']
        status = m['status']

        col1, col2, col3, col4 = st.columns([3, 3, 1, 1])
        col1.code(original_src)
        col2.code(original_tgt)
        col3.metric("Confidence", f"{conf:.0%}")
        if status == "mapped":
            col4.success("auto")
        else:
            col4.warning("review")

    # ─── Stage 3: Config generation ────────────────────
    st.divider()
    st.subheader("Step 4 — Generated config")

    with st.spinner("Generating YAML config..."):
        config_path = generate_config(parsed)

    with open(config_path) as f:
        config_yaml = f.read()

    st.code(config_yaml, language="yaml")
    st.download_button(
        label="Download config YAML",
        data=config_yaml,
        file_name=f"{parsed.tenant_id}_config.yaml",
        mime="text/yaml"
    )

    # ─── Stage 4: Simulation ───────────────────────────
    st.divider()
    st.subheader("Step 5 — Sandbox simulation")

    with st.spinner("Running simulation..."):
        results = run_simulation(config_path, fail_adapters=set(force_fail))

    passed = sum(1 for r in results if r['status'] == 'pass')
    failed = sum(1 for r in results if r['status'] == 'fail')
    warned = sum(1 for r in results if r['status'] == 'warn')

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total", len(results))
    col2.metric("Passed", passed)
    col3.metric("Failed", failed)
    col4.metric("Warnings", warned)

    for r in results:
        if r['status'] == 'pass':
            icon = "✅"
            fn = st.success
        elif r['status'] == 'fail':
            icon = "❌"
            fn = st.error
        else:
            icon = "⚠️"
            fn = st.warning

        fn(f"{icon} **{r['adapter']}** — {r['latency_ms']}ms — {r['status']}")
        if r['issues']:
            for issue in r['issues']:
                st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;{issue}")

    # ─── Final verdict ─────────────────────────────────
    st.divider()
    if failed == 0:
        st.success(
            f"All mandatory integrations passed. "
            f"Config is ready for deployment."
        )
    else:
        st.error(
            f"{failed} mandatory integration(s) failed. "
            f"Review issues before deploying."
        )
