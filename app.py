from __future__ import annotations

import time
from html import escape

import streamlit as st

from audit import load_audit_entries, record_pipeline_run
from config_gen import generate_config
from document_loader import DocumentLoadError, load_uploaded_document
from errors import FinSparkError
from healer import self_heal_config
from mapper import enrich_field_name, map_fields
from parser import ParsedBRD, parse_brd
from registry import delete_adapter, get_adapter, init_registry, list_adapters, upsert_adapter
from simulator import MOCK_RESPONSES, run_simulation, summarize_results
from tenants import authenticate_tenant, list_tenants, register_tenant

st.set_page_config(
    page_title="FinSpark Integration Engine",
    layout="wide",
)

init_registry()

if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = None
if "tenant_display_name" not in st.session_state:
    st.session_state.tenant_display_name = None

SERVICE_TYPE_OPTIONS = [
    "credit_bureau",
    "kyc",
    "gst",
    "bank_verify",
    "payment",
    "fraud",
    "other",
]
SERVICE_TYPE_LABELS = {
    "credit_bureau": "Credit Bureau",
    "kyc": "KYC",
    "gst": "GST",
    "bank_verify": "Bank Verify",
    "payment": "Payment",
    "fraud": "Fraud",
    "other": "Other",
}


def _tenant_label(tenant: dict) -> str:
    return f"{tenant['display_name']} ({tenant['tenant_id']})"


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
            :root {
                --finspark-text: #ffffff;
                --finspark-muted: #e2e8f0;
                --finspark-accent: #ff8fa3;
                --finspark-accent-strong: #ff4d6d;
                --finspark-surface: rgba(16, 10, 18, 0.92);
                --finspark-surface-strong: rgba(28, 12, 18, 0.98);
                --finspark-border: rgba(251, 113, 133, 0.28);
            }
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(244, 63, 94, 0.18), transparent 32%),
                    radial-gradient(circle at top right, rgba(251, 113, 133, 0.16), transparent 30%),
                    linear-gradient(180deg, #12070d 0%, #1f0a12 48%, #3b0913 100%);
            }
            [data-testid="stAppViewContainer"] > .main {
                color: var(--finspark-text);
            }
            [data-testid="stAppViewContainer"] .block-container {
                background: var(--finspark-surface);
                border: 1px solid var(--finspark-border);
                border-radius: 28px;
                box-shadow: 0 22px 48px rgba(2, 6, 23, 0.35);
                padding: 1.3rem 1.5rem 2rem;
                margin-top: 0.8rem;
                margin-bottom: 1.5rem;
                backdrop-filter: blur(8px);
            }

            /* ── Core text: force pure white everywhere ── */
            [data-testid="stAppViewContainer"] p,
            [data-testid="stAppViewContainer"] label,
            [data-testid="stAppViewContainer"] li,
            [data-testid="stAppViewContainer"] small,
            [data-testid="stAppViewContainer"] .stMarkdown,
            [data-testid="stAppViewContainer"] .stCaption,
            [data-testid="stAppViewContainer"] [data-testid="stMetricLabel"],
            [data-testid="stAppViewContainer"] [data-testid="stMetricValue"],
            [data-testid="stAppViewContainer"] h1,
            [data-testid="stAppViewContainer"] h2,
            [data-testid="stAppViewContainer"] h3,
            [data-testid="stAppViewContainer"] h4,
            [data-testid="stAppViewContainer"] h5,
            [data-testid="stAppViewContainer"] h6,
            [data-testid="stAppViewContainer"] span,
            [data-testid="stAppViewContainer"] div {
                color: var(--finspark-text);
            }

            /* ── Captions and muted text: light slate, still very readable ── */
            [data-testid="stAppViewContainer"] .stCaption,
            [data-testid="stAppViewContainer"] .section-note,
            [data-testid="stAppViewContainer"] [data-testid="stCaptionContainer"] {
                color: var(--finspark-muted) !important;
            }

            /* ── Metric values: bright white, larger weight ── */
            [data-testid="stAppViewContainer"] [data-testid="stMetricValue"] {
                color: #ffffff !important;
                font-weight: 700;
            }
            [data-testid="stAppViewContainer"] [data-testid="stMetricLabel"] {
                color: var(--finspark-muted) !important;
            }

            /* ── Inputs ── */
            [data-testid="stAppViewContainer"] textarea,
            [data-testid="stAppViewContainer"] input {
                color: #ffffff !important;
                background: var(--finspark-surface-strong) !important;
                caret-color: var(--finspark-accent);
            }
            [data-testid="stAppViewContainer"] [data-baseweb="select"] *,
            [data-testid="stAppViewContainer"] [data-baseweb="radio"] *,
            [data-testid="stAppViewContainer"] [data-baseweb="popover"] * {
                color: #ffffff !important;
            }
            [data-testid="stAppViewContainer"] [data-baseweb="input"] {
                background: var(--finspark-surface-strong) !important;
            }
            [data-testid="stAppViewContainer"] [data-baseweb="select"] > div,
            [data-testid="stAppViewContainer"] [data-baseweb="textarea"] > div {
                background: var(--finspark-surface-strong) !important;
                border-color: rgba(251, 113, 133, 0.28) !important;
            }

            /* ── Form labels: bright accent, clearly readable ── */
            [data-testid="stAppViewContainer"] .stRadio label,
            [data-testid="stAppViewContainer"] .stFileUploader label,
            [data-testid="stAppViewContainer"] .stTextArea label,
            [data-testid="stAppViewContainer"] .stTextInput label,
            [data-testid="stAppViewContainer"] .stSelectbox label,
            [data-testid="stAppViewContainer"] .stMultiSelect label,
            [data-testid="stAppViewContainer"] .stNumberInput label {
                color: var(--finspark-accent) !important;
                font-weight: 600;
            }

            /* ── Code blocks: bright near-white ── */
            [data-testid="stAppViewContainer"] code,
            [data-testid="stAppViewContainer"] pre,
            [data-testid="stAppViewContainer"] pre * {
                color: #f8fafc !important;
                background: rgba(0, 0, 0, 0.35) !important;
            }

            /* ── Sidebar ── */
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #0f172a 0%, #162033 100%);
            }
            [data-testid="stSidebar"] *,
            [data-testid="stSidebar"] p,
            [data-testid="stSidebar"] label,
            [data-testid="stSidebar"] span,
            [data-testid="stSidebar"] div,
            [data-testid="stSidebar"] .stMarkdown p {
                color: #f1f5f9 !important;
            }
            [data-testid="stSidebar"] .stCaption,
            [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
                color: #cbd5e1 !important;
            }
            [data-testid="stSidebar"] label {
                color: #93c5fd !important;
                font-weight: 600;
            }
            [data-testid="stSidebar"] input,
            [data-testid="stSidebar"] textarea {
                color: #f1f5f9 !important;
                background: rgba(15, 23, 42, 0.85) !important;
            }
            [data-testid="stSidebar"] [data-baseweb="select"] * {
                color: #f1f5f9 !important;
            }
            [data-testid="stSidebar"] [data-baseweb="select"] > div {
                background: rgba(15, 23, 42, 0.85) !important;
            }

            /* ── Alert / info / success / error boxes ── */
            [data-testid="stAppViewContainer"] .stAlert p,
            [data-testid="stAppViewContainer"] .stAlert div,
            [data-testid="stAppViewContainer"] .stAlert span {
                color: #0f172a !important;
            }

            /* ── Dataframe ── */
            [data-testid="stAppViewContainer"] .stDataFrame,
            [data-testid="stAppViewContainer"] .stDataFrame * {
                color: #f1f5f9 !important;
            }

            /* ── Hero section ── */
            .hero-shell {
                padding: 1.4rem 1.6rem;
                border-radius: 24px;
                background: linear-gradient(135deg, #0f172a 0%, #12304a 55%, #136b77 100%);
                color: #f8fbff;
                box-shadow: 0 22px 48px rgba(15, 23, 42, 0.18);
                margin-bottom: 1rem;
            }
            .hero-shell h1 {
                margin: 0;
                font-size: 2.1rem;
                line-height: 1.1;
                letter-spacing: -0.03em;
                color: #ffffff !important;
            }
            .hero-shell p,
            .hero-shell span {
                color: rgba(248, 251, 255, 0.92) !important;
                font-size: 1rem;
                max-width: 54rem;
            }
            .hero-pills {
                display: flex;
                flex-wrap: wrap;
                gap: 0.55rem;
                margin-top: 1rem;
            }
            .hero-pill {
                padding: 0.38rem 0.72rem;
                border: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.14);
                font-size: 0.82rem;
                color: #ffffff !important;
                font-weight: 500;
            }

            /* ── Service cards ── */
            .service-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 0.85rem;
                margin: 0.75rem 0 0.25rem;
            }
            .service-card {
                background: rgba(15, 5, 10, 0.82);
                border: 1px solid rgba(251, 113, 133, 0.22);
                border-radius: 20px;
                padding: 1rem;
                box-shadow: 0 16px 36px rgba(2, 6, 23, 0.22);
            }
            .service-card h4 {
                margin: 0 0 0.35rem;
                font-size: 1rem;
                color: #ffffff !important;
                font-weight: 700;
            }
            .service-meta {
                color: #cbd5e1 !important;
                font-size: 0.88rem;
                margin-bottom: 0.6rem;
            }
            .service-badge {
                display: inline-block;
                margin-right: 0.4rem;
                margin-top: 0.3rem;
                padding: 0.24rem 0.55rem;
                border-radius: 999px;
                font-size: 0.76rem;
                font-weight: 600;
            }
            .service-badge.type {
                background: rgba(251, 113, 133, 0.22);
                color: #ffffff !important;
            }
            .service-badge.mandatory {
                background: rgba(244, 63, 94, 0.32);
                color: #ffffff !important;
            }
            .service-badge.optional {
                background: rgba(190, 24, 93, 0.22);
                color: #f1f5f9 !important;
            }

            /* ── Section helpers ── */
            .section-note {
                color: var(--finspark-muted) !important;
                margin-top: -0.35rem;
                margin-bottom: 0.8rem;
                font-size: 0.92rem;
            }
            .section-title {
                margin: 0.25rem 0 0.4rem;
                font-size: 1.35rem;
                line-height: 1.2;
                letter-spacing: -0.02em;
                color: var(--finspark-accent) !important;
                font-weight: 700;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_hero(registry_rows: list[dict]) -> None:
    active_adapters = sum(1 for row in registry_rows if row["active"])
    tenant_label = st.session_state.tenant_display_name or "Sign in to unlock a tenant workspace"
    st.markdown(
        f"""
        <section class="hero-shell">
            <h1>FinSpark Integration Studio</h1>
            <p>
                Turn BRDs into tenant-scoped fintech integration configs, validate them in sandbox,
                heal breakages, and keep a full audit trail ready for judges and reviewers.
            </p>
            <div class="hero-pills">
                <span class="hero-pill">Tenant: {escape(tenant_label)}</span>
                <span class="hero-pill">Active adapters: {active_adapters}</span>
                <span class="hero-pill">Dynamic registry onboarding enabled</span>
                <span class="hero-pill">SQLite-backed configuration flow</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_service_cards(services: list) -> None:
    cards = []
    for service in services:
        mandatory_class = "mandatory" if service.mandatory else "optional"
        mandatory_label = "Mandatory" if service.mandatory else "Optional"
        cards.append(
            f"""
            <article class="service-card">
                <h4>{escape(service.name)}</h4>
                <div class="service-meta">{escape(service.provider)}</div>
                <span class="service-badge type">{escape(SERVICE_TYPE_LABELS.get(service.type, service.type.title()))}</span>
                <span class="service-badge {mandatory_class}">{mandatory_label}</span>
            </article>
            """
        )
    st.markdown(f"<div class='service-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def _render_section_title(title: str) -> None:
    st.markdown(
        f"<h3 class='section-title'>{escape(title)}</h3>",
        unsafe_allow_html=True,
    )


def _default_timeout(service_type: str) -> int:
    timeout_defaults = {
        "credit_bureau": 3000,
        "kyc": 2000,
        "gst": 2500,
        "bank_verify": 1500,
        "payment": 1800,
        "fraud": 2200,
    }
    return timeout_defaults.get(service_type, 2000)


def _default_adapter_name(provider: str, service_type: str) -> str:
    provider_slug = provider.strip().lower().replace(" ", "-")
    service_slug = service_type.replace("_", "-")
    return f"{provider_slug}-{service_slug}-adapter"


def _missing_registry_services(parsed: ParsedBRD) -> list:
    missing = []
    seen = set()
    for service in parsed.services:
        provider_key = service.provider.strip().lower()
        if provider_key in seen:
            continue
        seen.add(provider_key)
        if get_adapter(service.provider) is None:
            missing.append(service)
    return missing


_inject_styles()
registry_rows = list_adapters(include_inactive=True)
_render_hero(registry_rows)

with st.sidebar:
    st.subheader("Tenant access")
    tenants = list_tenants()

    if st.session_state.tenant_id:
        st.success(
            f"Logged in as {st.session_state.tenant_display_name} "
            f"({st.session_state.tenant_id})"
        )
        if st.button("Log out", width="stretch"):
            st.session_state.tenant_id = None
            st.session_state.tenant_display_name = None
            st.rerun()
    else:
        if tenants:
            with st.form("login_form"):
                selected_tenant = st.selectbox(
                    "Tenant",
                    options=tenants,
                    format_func=_tenant_label,
                )
                login_code = st.text_input("Access code", type="password")
                login_submit = st.form_submit_button("Log in", width="stretch")

            if login_submit:
                if authenticate_tenant(selected_tenant["tenant_id"], login_code):
                    st.session_state.tenant_id = selected_tenant["tenant_id"]
                    st.session_state.tenant_display_name = selected_tenant["display_name"]
                    st.rerun()
                st.error("Invalid tenant or access code.")

        with st.form("create_tenant_form"):
            tenant_name = st.text_input("Create tenant")
            tenant_code = st.text_input("Set access code", type="password")
            create_submit = st.form_submit_button("Create tenant", width="stretch")

        if create_submit:
            try:
                tenant_record = register_tenant(tenant_name, tenant_code)
                st.session_state.tenant_id = tenant_record["tenant_id"]
                st.session_state.tenant_display_name = tenant_record["display_name"]
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.divider()
    st.subheader("Pipeline controls")
    sample_brd = (
        f"{st.session_state.tenant_display_name or 'Acme Lending'} requires CIBIL for "
        "credit bureau checks (mandatory). UIDAI Aadhaar eKYC is mandatory for all "
        "borrowers. GST verification via NIC portal is optional for MSME loans. "
        "Razorpay penny drop is mandatory for bank account validation."
    )
    force_fail = st.multiselect(
        "Force adapter failure (for demo)",
        options=list(MOCK_RESPONSES.keys()),
        default=[],
    )

    st.divider()
    st.caption("Adapter registry")
    st.dataframe(registry_rows, width="stretch", hide_index=True)

    with st.expander("Manage registry"):
        with st.form("upsert_registry_form"):
            provider = st.text_input("Provider")
            service_type = st.selectbox(
                "Service type",
                options=SERVICE_TYPE_OPTIONS,
            )
            adapter = st.text_input("Adapter name")
            version = st.text_input(
                "Version(s)",
                value="v1.0",
                help="Use a comma-separated catalog like `v1.0, v1.1`. FinSpark will select the latest approved version.",
            )
            timeout_ms = st.number_input("Timeout (ms)", min_value=100, value=2000, step=100)
            backup_provider = st.text_input("Backup provider")
            notes = st.text_area("Notes")
            save_registry = st.form_submit_button("Save adapter", width="stretch")

        if save_registry:
            try:
                upsert_adapter(
                    provider=provider,
                    service_type=service_type,
                    adapter=adapter,
                    version=version,
                    timeout_ms=int(timeout_ms),
                    backup_provider=backup_provider or None,
                    notes=notes,
                )
                st.success("Registry updated.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        active_providers = [row["provider"] for row in registry_rows if row["active"]]
        if active_providers:
            provider_to_disable = st.selectbox(
                "Disable provider",
                options=active_providers,
            )
            if st.button("Disable adapter", width="stretch"):
                delete_adapter(provider_to_disable)
                st.warning(f"{provider_to_disable} marked inactive.")
                st.rerun()

if not st.session_state.tenant_id:
    st.info("Create or log into a tenant from the sidebar to run a scoped pipeline.")
    st.stop()

_render_section_title("Step 1 - Provide your BRD")
st.markdown(
    "<p class='section-note'>Paste a BRD or upload a PDF, DOCX, or text document. FinSpark will extract the text, detect providers, build config, simulate adapters, and log the run.</p>",
    unsafe_allow_html=True,
)
input_mode = st.radio(
    "Input source",
    options=["Paste text", "Upload file"],
    horizontal=True,
)

source_label = "Pasted text"
brd_input = ""

if input_mode == "Paste text":
    brd_input = st.text_area(
        label="Requirement document",
        value=sample_brd,
        height=160,
        placeholder="Paste your BRD or SOW text here...",
        key="brd_input",
    )
else:
    uploaded_file = st.file_uploader(
        "Upload BRD or SOW",
        type=["pdf", "docx", "txt", "md", "brd"],
        help="PDF and DOCX uploads are converted into text before parsing.",
    )
    if uploaded_file is None:
        st.caption("Supported formats: PDF, DOCX, TXT, MD, and BRD text files.")
    else:
        try:
            uploaded_document = load_uploaded_document(
                uploaded_file.name,
                uploaded_file.getvalue(),
            )
            brd_input = uploaded_document.text
            source_label = uploaded_document.name
            st.success(
                f"Loaded `{uploaded_document.name}` with {len(uploaded_document.text):,} characters."
            )
            with st.expander("Preview extracted text"):
                st.text_area(
                    "Extracted content",
                    value=uploaded_document.text,
                    height=220,
                    disabled=True,
                    label_visibility="collapsed",
                )
        except DocumentLoadError as exc:
            st.error(str(exc))

run_btn = st.button("Run pipeline", type="primary", width="stretch")

if run_btn:
    if not brd_input.strip():
        if input_mode == "Upload file":
            st.error("Please upload a readable BRD file before running.")
        else:
            st.error("Please paste a BRD before running.")
        st.stop()

    started_at = time.perf_counter()
    try:
        st.divider()
        _render_section_title("Step 2 - Parsed requirements")
        st.markdown(
            "<p class='section-note'>Detected services are summarized below before registry resolution and config generation.</p>",
            unsafe_allow_html=True,
        )
        with st.spinner("Parsing BRD with Llama 3.3 or fallback rules..."):
            parsed_result = parse_brd(brd_input)

        parsed = ParsedBRD(
            tenant_id=st.session_state.tenant_id,
            services=parsed_result.services,
            parse_mode=parsed_result.parse_mode,
            parser_notes=parsed_result.parser_notes,
        )

        if not parsed.services:
            st.error("No supported integrations were detected in the BRD.")
            st.stop()

        st.caption(f"Input source: {source_label}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Tenant", parsed.tenant_id)
        col2.metric("Services found", len(parsed.services))
        col3.metric("Mandatory", sum(1 for service in parsed.services if service.mandatory))
        col4.metric("Parse mode", parsed.parse_mode)

        _render_service_cards(parsed.services)

        with st.expander("View extraction diagnostics"):
            for note in parsed.parser_notes:
                st.write(f"- {note}")
            for service in parsed.services:
                st.markdown(
                    f"**{service.provider}** | `{service.type}` | confidence `{service.confidence:.0%}`"
                )
                for signal in service.evidence:
                    st.caption(signal)

        with st.expander("View raw JSON"):
            st.json(parsed.model_dump())

        missing_registry_services = _missing_registry_services(parsed)
        if missing_registry_services:
            st.divider()
            _render_section_title("Resolve Missing Registry Entries")
            st.warning(
                "Some providers from this BRD are not in the adapter registry yet. "
                "Add them below, then click Run pipeline again."
            )

            for service in missing_registry_services:
                with st.form(f"missing_registry_{service.provider}_{service.type}"):
                    provider_value = st.text_input(
                        "Provider",
                        value=service.provider,
                        key=f"missing_provider_{service.provider}_{service.type}",
                    )
                    service_type = st.selectbox(
                        "Service type",
                        options=SERVICE_TYPE_OPTIONS,
                        index=SERVICE_TYPE_OPTIONS.index(
                            service.type if service.type in SERVICE_TYPE_OPTIONS else "other"
                        ),
                        key=f"missing_service_type_{service.provider}_{service.type}",
                    )
                    adapter_name = st.text_input(
                        "Adapter name",
                        value=_default_adapter_name(service.provider, service.type),
                        key=f"missing_adapter_{service.provider}_{service.type}",
                    )
                    version = st.text_input(
                        "Version(s)",
                        value="v1.0",
                        help="Use a comma-separated catalog like `v1.0, v1.1`. FinSpark will select the latest approved version.",
                        key=f"missing_version_{service.provider}_{service.type}",
                    )
                    timeout_ms = st.number_input(
                        "Timeout (ms)",
                        min_value=100,
                        value=_default_timeout(service.type),
                        step=100,
                        key=f"missing_timeout_{service.provider}_{service.type}",
                    )
                    backup_provider = st.text_input(
                        "Backup provider",
                        value="",
                        key=f"missing_backup_{service.provider}_{service.type}",
                    )
                    notes = st.text_area(
                        "Notes",
                        value=f"Added dynamically from BRD-detected provider {service.provider}.",
                        key=f"missing_notes_{service.provider}_{service.type}",
                    )
                    add_missing_registry = st.form_submit_button(
                        f"Add {service.provider} to registry",
                        width="stretch",
                    )

                if add_missing_registry:
                    try:
                        upsert_adapter(
                            provider=provider_value,
                            service_type=service_type,
                            adapter=adapter_name,
                            version=version,
                            timeout_ms=int(timeout_ms),
                            backup_provider=backup_provider or None,
                            notes=notes,
                        )
                        st.success(f"{provider_value} added to registry. Click Run pipeline again.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

            st.stop()

        st.divider()
        _render_section_title("Step 3 - Field mappings (reference CIBIL adapter)")
        st.markdown(
            "<p class='section-note'>Mappings stay demo-friendly offline and can switch to embeddings when explicitly enabled.</p>",
            unsafe_allow_html=True,
        )

        source_fields = [
            "borrower.pan_number",
            "borrower.date_of_birth",
            "borrower.mobile_number",
            "loan.amount_requested",
            "loan.tenure_months",
            "loan.product_type",
        ]
        target_fields = [
            "applicant.panCard",
            "applicant.dateOfBirth",
            "applicant.mobileNumber",
            "enquiry.loanAmount",
            "enquiry.tenureInMonths",
            "enquiry.creditProductType",
        ]

        with st.spinner("Running semantic field mapping..."):
            enriched_source = [enrich_field_name(value) for value in source_fields]
            enriched_target = [enrich_field_name(value) for value in target_fields]
            mappings = map_fields(enriched_source, enriched_target)

        for index, mapping in enumerate(mappings):
            target_index = enriched_target.index(mapping["target"])
            col1, col2, col3, col4 = st.columns([3, 3, 1, 1])
            col1.code(source_fields[index])
            col2.code(target_fields[target_index])
            col3.metric("Confidence", f"{mapping['confidence']:.0%}")
            if mapping["status"] == "mapped":
                col4.success("auto")
            else:
                col4.warning("review")

        st.divider()
        _render_section_title("Step 4 - Generated config")
        st.markdown(
            "<p class='section-note'>Configs are versioned per tenant, resolved against the latest approved adapter versions, and compared against the previous version in plain English.</p>",
            unsafe_allow_html=True,
        )
        with st.spinner("Generating YAML config..."):
            generated_config = generate_config(parsed)

        config_yaml = generated_config.current_path.read_text(encoding="utf-8")
        st.info(generated_config.diff_summary)
        st.caption(
            f"Current config version `{generated_config.version_label}` | previous "
            f"`{generated_config.previous_version_label or 'none'}` | history "
            f"`{generated_config.version_history_count}`"
        )
        st.code(config_yaml, language="yaml")
        st.download_button(
            label="Download config YAML",
            data=config_yaml,
            file_name=f"{parsed.tenant_id}_config.yaml",
            mime="text/yaml",
        )

        st.divider()
        _render_section_title("Step 5 - Sandbox simulation")
        st.markdown(
            "<p class='section-note'>Simulation validates adapter payloads, registry policy rules, fallback chains, and approved adapter versions for each integration.</p>",
            unsafe_allow_html=True,
        )
        with st.spinner("Running simulation..."):
            results = run_simulation(generated_config.current_path, fail_adapters=set(force_fail))

        healing_report = None
        if any(result["status"] == "fail" for result in results):
            with st.spinner("Applying self-healing and re-running simulation..."):
                healing_report = self_heal_config(
                    generated_config.current_path,
                    fail_adapters=set(force_fail),
                    max_retries=3,
                )
                results = healing_report["results"]
                config_yaml = healing_report["config_yaml"]

        summary = summarize_results(results)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total", summary["total"])
        col2.metric("Passed", summary["passed"])
        col3.metric("Failed", summary["failed"])
        col4.metric("Warnings", summary["warnings"])

        for result in results:
            if result["status"] == "pass":
                icon = "[PASS]"
                render = st.success
            elif result["status"] == "fail":
                icon = "[FAIL]"
                render = st.error
            else:
                icon = "[WARN]"
                render = st.warning

            render(f"{icon} **{result['adapter']}** - {result['latency_ms']}ms - {result['status']}")
            st.caption(
                f"Technical: {result.get('technical_status', 'unknown')} | "
                f"Policy: {result.get('policy_status', 'unknown')}"
            )
            for issue in result["issues"]:
                st.caption(f"    {issue}")

        if healing_report and healing_report["attempt_count"]:
            st.divider()
            _render_section_title("Step 6 - Self-healing actions")
            st.markdown(
                "<p class='section-note'>FinSpark applies bounded fixes, restores registry-aligned controls, explains each attempt, and reruns the simulation automatically.</p>",
                unsafe_allow_html=True,
            )
            for attempt in healing_report["attempts"]:
                with st.expander(f"Attempt {attempt['attempt']}", expanded=True):
                    for diagnosis in attempt["diagnoses"]:
                        st.write(diagnosis)
                    for action in attempt["actions"]:
                        st.code(action, language=None)
                    st.caption(attempt["diff_summary"])

            _render_section_title("Healed config")
            st.code(config_yaml, language="yaml")

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        audit_entry, audit_path = record_pipeline_run(
            tenant_id=parsed.tenant_id,
            parsed_payload=parsed.model_dump(),
            simulation_results=results,
            duration_ms=duration_ms,
            config_path=generated_config.current_path,
            healed=bool(healing_report and healing_report["healed"]),
            healing_attempts=healing_report["attempt_count"] if healing_report else 0,
            diff_summary=generated_config.diff_summary,
        )

        st.divider()
        _render_section_title("Step 7 - Audit trail")
        st.markdown(
            "<p class='section-note'>Every pipeline run is appended to the tenant audit log with timing, parser diagnostics, and policy-aware simulation details.</p>",
            unsafe_allow_html=True,
        )
        st.caption(f"Appended run log at `{audit_path}`")
        st.json(audit_entry)

        recent_entries = load_audit_entries(parsed.tenant_id, limit=5)
        if recent_entries:
            st.caption("Recent runs for this tenant")
            st.dataframe(recent_entries, width="stretch")

        st.divider()
        if summary["failed"] == 0:
            st.success("All mandatory integrations passed. Config is ready for deployment.")
        else:
            st.error(
                f"{summary['failed']} mandatory integration(s) failed. Review issues before deploying."
            )
    except FinSparkError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error("Unexpected pipeline error. The app stayed running so you can correct the input and retry.")
        st.exception(exc)
        st.stop()
