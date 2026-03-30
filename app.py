from __future__ import annotations

import time

import streamlit as st

from audit import load_audit_entries, record_pipeline_run
from config_gen import generate_config
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


def _tenant_label(tenant: dict) -> str:
    return f"{tenant['display_name']} ({tenant['tenant_id']})"


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


st.title("FinSpark - AI Integration Orchestration Engine")
st.caption("Transform requirement documents into production-ready integration configs")
st.divider()

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
    registry_rows = list_adapters(include_inactive=True)
    st.dataframe(registry_rows, width="stretch", hide_index=True)

    with st.expander("Manage registry"):
        with st.form("upsert_registry_form"):
            provider = st.text_input("Provider")
            service_type = st.selectbox(
                "Service type",
                options=[
                    "credit_bureau",
                    "kyc",
                    "gst",
                    "bank_verify",
                    "payment",
                    "fraud",
                    "other",
                ],
            )
            adapter = st.text_input("Adapter name")
            version = st.text_input("Version", value="v1.0")
            timeout_ms = st.number_input("Timeout (ms)", min_value=100, value=2000, step=100)
            backup_provider = st.text_input("Backup provider")
            notes = st.text_area("Notes")
            save_registry = st.form_submit_button("Save adapter", width="stretch")

        if save_registry:
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

st.subheader("Step 1 - Paste your BRD")
brd_input = st.text_area(
    label="Requirement document",
    value=sample_brd,
    height=160,
    placeholder="Paste your BRD or SOW text here...",
    key="brd_input",
)

run_btn = st.button("Run pipeline", type="primary", width="stretch")

if run_btn:
    if not brd_input.strip():
        st.error("Please paste a BRD before running.")
        st.stop()

    started_at = time.perf_counter()

    st.divider()
    st.subheader("Step 2 - Parsed requirements")
    with st.spinner("Parsing BRD with Llama 3.3 or fallback rules..."):
        parsed = parse_brd(brd_input)

    parsed = ParsedBRD(
        tenant_id=st.session_state.tenant_id,
        services=parsed.services,
    )

    if not parsed.services:
        st.error("No supported integrations were detected in the BRD.")
        st.stop()

    col1, col2, col3 = st.columns(3)
    col1.metric("Tenant", parsed.tenant_id)
    col2.metric("Services found", len(parsed.services))
    col3.metric("Mandatory", sum(1 for service in parsed.services if service.mandatory))

    for service in parsed.services:
        badge = "mandatory" if service.mandatory else "optional"
        color = "red" if service.mandatory else "gray"
        st.markdown(
            f"**{service.name}**  `{service.type}`  `{service.provider}`  :{color}[{badge}]"
        )

    with st.expander("View raw JSON"):
        st.json(parsed.model_dump())

    missing_registry_services = _missing_registry_services(parsed)
    if missing_registry_services:
        st.divider()
        st.subheader("Resolve Missing Registry Entries")
        st.warning(
            "Some providers from this BRD are not in the adapter registry yet. "
            "Add them below, then click Run pipeline again."
        )

        for service in missing_registry_services:
            with st.form(f"missing_registry_{service.provider}_{service.type}"):
                st.text_input(
                    "Provider",
                    value=service.provider,
                    key=f"missing_provider_{service.provider}_{service.type}",
                )
                service_type = st.selectbox(
                    "Service type",
                    options=[
                        "credit_bureau",
                        "kyc",
                        "gst",
                        "bank_verify",
                        "payment",
                        "fraud",
                        "other",
                    ],
                    index=[
                        "credit_bureau",
                        "kyc",
                        "gst",
                        "bank_verify",
                        "payment",
                        "fraud",
                        "other",
                    ].index(service.type if service.type in {
                        "credit_bureau",
                        "kyc",
                        "gst",
                        "bank_verify",
                        "payment",
                        "fraud",
                        "other",
                    } else "other"),
                    key=f"missing_service_type_{service.provider}_{service.type}",
                )
                adapter_name = st.text_input(
                    "Adapter name",
                    value=_default_adapter_name(service.provider, service.type),
                    key=f"missing_adapter_{service.provider}_{service.type}",
                )
                version = st.text_input(
                    "Version",
                    value="v1.0",
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
                upsert_adapter(
                    provider=service.provider,
                    service_type=service_type,
                    adapter=adapter_name,
                    version=version,
                    timeout_ms=int(timeout_ms),
                    backup_provider=backup_provider or None,
                    notes=notes,
                )
                st.rerun()

        st.stop()

    st.divider()
    st.subheader("Step 3 - Field mappings (reference CIBIL adapter)")

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
    st.subheader("Step 4 - Generated config")
    with st.spinner("Generating YAML config..."):
        generated_config = generate_config(parsed)

    config_yaml = generated_config.current_path.read_text(encoding="utf-8")
    st.info(generated_config.diff_summary)
    st.code(config_yaml, language="yaml")
    st.download_button(
        label="Download config YAML",
        data=config_yaml,
        file_name=f"{parsed.tenant_id}_config.yaml",
        mime="text/yaml",
    )

    st.divider()
    st.subheader("Step 5 - Sandbox simulation")
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
        for issue in result["issues"]:
            st.caption(f"    {issue}")

    if healing_report and healing_report["attempt_count"]:
        st.divider()
        st.subheader("Step 6 - Self-healing actions")
        for attempt in healing_report["attempts"]:
            with st.expander(f"Attempt {attempt['attempt']}", expanded=True):
                for diagnosis in attempt["diagnoses"]:
                    st.write(diagnosis)
                for action in attempt["actions"]:
                    st.code(action, language=None)
                st.caption(attempt["diff_summary"])

        st.subheader("Healed config")
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
    st.subheader("Step 7 - Audit trail")
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
