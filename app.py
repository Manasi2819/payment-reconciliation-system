"""
app.py — Streamlit Web Application for Payment Reconciliation System

Interactive dashboard that allows users to:
    1. Generate synthetic transaction & settlement datasets
    2. Run the multi-agent reconciliation engine
    3. View summary metrics, charts, and detailed issue reports
    4. Filter and download results as CSV

Usage:
    streamlit run app.py
"""

import io
from typing import Any, Dict

import pandas as pd
import streamlit as st

from data_generation import generate_datasets
from coordinator import ReconciliationCoordinator

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Payment Reconciliation System",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for premium look
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    /* Main background */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #1a1a2e 50%, #16213e 100%);
    }

    /* Metric cards */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 16px 20px;
        backdrop-filter: blur(10px);
    }
    div[data-testid="stMetric"] label {
        color: #a0aec0 !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #e2e8f0 !important;
        font-weight: 700 !important;
    }

    /* Section headers */
    .section-header {
        background: linear-gradient(90deg, rgba(99, 102, 241, 0.15), transparent);
        border-left: 4px solid #6366f1;
        padding: 12px 20px;
        border-radius: 0 8px 8px 0;
        margin: 24px 0 16px 0;
    }
    .section-header h3 {
        margin: 0;
        color: #c7d2fe;
        font-weight: 600;
    }

    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 2rem;
        font-weight: 600;
        font-size: 1rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
        transform: translateY(-1px);
    }

    /* Download buttons */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #059669, #10b981);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(5, 150, 105, 0.3);
    }

    /* DataFrames */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: rgba(15, 12, 41, 0.95);
        border-right: 1px solid rgba(255, 255, 255, 0.06);
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 8px 20px;
    }

    /* Info/success/warning boxes */
    .stAlert {
        border-radius: 8px;
    }

    /* Selectbox */
    .stSelectbox > div > div {
        border-radius: 8px;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Severity badges */
    .severity-high { color: #ef4444; font-weight: 700; }
    .severity-medium { color: #f59e0b; font-weight: 700; }
    .severity-low { color: #22c55e; font-weight: 700; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def section_header(title: str, icon: str = "") -> None:
    """Render a styled section header."""
    st.markdown(
        f'<div class="section-header"><h3>{icon} {title}</h3></div>',
        unsafe_allow_html=True,
    )


def severity_color(severity: str) -> str:
    """Return hex color for a severity level."""
    return {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(
        severity.lower(), "#94a3b8"
    )


def build_summary_csv(summary: Dict[str, Any]) -> str:
    """Convert summary dict to a CSV string."""
    rows = []
    for key in ["total_transactions", "total_settlements", "total_matched",
                 "total_mismatched", "total_issues"]:
        rows.append({"metric": key, "value": summary.get(key, 0)})
    for it, count in summary.get("breakdown_by_issue_type", {}).items():
        rows.append({"metric": f"issue_type:{it}", "value": count})
    for sev, count in summary.get("breakdown_by_severity", {}).items():
        rows.append({"metric": f"severity:{sev}", "value": count})
    return pd.DataFrame(rows).to_csv(index=False)


# ---------------------------------------------------------------------------
# Sidebar — controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🎛️ Controls")
    st.markdown("---")

    # Seed selector
    seed = st.number_input("Random Seed", min_value=1, max_value=9999, value=42,
                           help="Controls reproducibility of synthetic data")

    st.markdown("---")

    # Step 1: Generate data
    st.markdown("### Step 1")
    generate_clicked = st.button("🗂️  Generate Data", use_container_width=True,
                                  key="btn_generate")

    st.markdown("### Step 2")
    run_clicked = st.button("🔍  Run Reconciliation", use_container_width=True,
                             key="btn_run")

    st.markdown("---")
    st.markdown(
        "<small style='color:#64748b'>Built with Python · pandas · Streamlit</small>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session state management
# ---------------------------------------------------------------------------

if generate_clicked:
    with st.spinner("Generating synthetic datasets..."):
        txns, stls, manifest = generate_datasets(seed=seed)
        st.session_state["transactions"] = txns
        st.session_state["settlements"] = stls
        st.session_state["manifest"] = manifest
        # Clear old results when regenerating
        st.session_state.pop("detailed_report", None)
        st.session_state.pop("summary_report", None)

if run_clicked:
    if "transactions" not in st.session_state:
        st.sidebar.error("⚠️ Generate data first!")
    else:
        with st.spinner("Running 7 reconciliation agents..."):
            coord = ReconciliationCoordinator(
                st.session_state["transactions"],
                st.session_state["settlements"],
            )
            coord.run()
            st.session_state["detailed_report"] = coord.get_detailed_report()
            st.session_state["summary_report"] = coord.get_summary_report()


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

# ── Header ─────────────────────────────────────────────────────────────────

st.markdown("""
<div style="text-align:center; padding: 20px 0 10px 0;">
    <h1 style="color:#e2e8f0; font-size:2.4rem; font-weight:800; letter-spacing:-0.5px;">
        🏦 Payment Reconciliation System
    </h1>
    <p style="color:#94a3b8; font-size:1.05rem; max-width:700px; margin:0 auto;">
        Multi-agent engine that detects mismatches between internal transaction records
        and bank settlement data — rounding errors, missing settlements,
        duplicate entries, orphaned refunds, and more.
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")


# ── Data Overview ──────────────────────────────────────────────────────────

if "transactions" in st.session_state:
    txns: pd.DataFrame = st.session_state["transactions"]
    stls: pd.DataFrame = st.session_state["settlements"]
    manifest: Dict = st.session_state["manifest"]

    section_header("Data Overview", "📊")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Transactions", f"{len(txns):,}")
    col2.metric("Settlements", f"{len(stls):,}")
    col3.metric("Unique Txn IDs", f"{txns['transaction_id'].nunique():,}")
    col4.metric("Issue Types Injected", str(len(manifest)))

    # Injected issues manifest
    with st.expander("📋 Injected Issues Manifest", expanded=False):
        manifest_df = pd.DataFrame([
            {"Issue Type": k, "Count": len(v)} for k, v in manifest.items()
        ])
        st.dataframe(manifest_df, use_container_width=True, hide_index=True)

    # Sample data viewer
    section_header("Sample Data Viewer", "🔎")
    tab_txn, tab_stl = st.tabs(["📄 Transactions", "📄 Settlements"])
    with tab_txn:
        st.dataframe(txns.head(10), use_container_width=True, hide_index=True)
    with tab_stl:
        st.dataframe(stls.head(10), use_container_width=True, hide_index=True)

else:
    st.info("👈 Click **Generate Data** in the sidebar to start.")


# ── Reconciliation Results ────────────────────────────────────────────────

if "detailed_report" in st.session_state:
    detailed: pd.DataFrame = st.session_state["detailed_report"]
    summary: Dict[str, Any] = st.session_state["summary_report"]

    st.markdown("---")
    section_header("Reconciliation Results", "⚡")

    # ── Summary metrics ───────────────────────────────────────────────────

    sev_breakdown = summary.get("breakdown_by_severity", {})
    high = sev_breakdown.get("high", 0)
    medium = sev_breakdown.get("medium", 0)
    low = sev_breakdown.get("low", 0)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total Transactions", f"{summary['total_transactions']:,}")
    m2.metric("Matched", f"{summary['total_matched']:,}")
    m3.metric("Total Issues", f"{summary['total_issues']:,}")
    m4.metric("🔴 High", str(high))
    m5.metric("🟡 Medium", str(medium))
    m6.metric("🟢 Low", str(low))

    # ── Issue breakdown chart ────────────────────────────────────────────

    section_header("Issue Breakdown", "📈")

    issue_counts = summary.get("breakdown_by_issue_type", {})
    if issue_counts:
        chart_df = (
            pd.DataFrame(
                list(issue_counts.items()), columns=["Issue Type", "Count"]
            )
            .sort_values("Count", ascending=True)
        )

        st.bar_chart(
            chart_df.set_index("Issue Type"),
            horizontal=True,
            color="#6366f1",
        )

    # ── Severity distribution ────────────────────────────────────────────

    if sev_breakdown:
        sev_col1, sev_col2 = st.columns([1, 2])
        with sev_col1:
            st.markdown("#### Severity Distribution")
            sev_df = pd.DataFrame(
                list(sev_breakdown.items()), columns=["Severity", "Count"]
            )
            st.dataframe(sev_df, use_container_width=True, hide_index=True)
        with sev_col2:
            st.bar_chart(
                sev_df.set_index("Severity"),
                color="#8b5cf6",
            )

    # ── Detailed report with filters ─────────────────────────────────────

    st.markdown("---")
    section_header("Detailed Mismatch Report", "📝")

    if not detailed.empty:
        filter_col1, filter_col2 = st.columns(2)

        with filter_col1:
            issue_types = ["All"] + sorted(detailed["issue_type"].unique().tolist())
            selected_type = st.selectbox("Filter by Issue Type", issue_types)

        with filter_col2:
            severities = ["All"] + sorted(detailed["severity"].unique().tolist())
            selected_severity = st.selectbox("Filter by Severity", severities)

        # Apply filters
        filtered = detailed.copy()
        if selected_type != "All":
            filtered = filtered[filtered["issue_type"] == selected_type]
        if selected_severity != "All":
            filtered = filtered[filtered["severity"] == selected_severity]

        st.markdown(
            f"<p style='color:#94a3b8;'>Showing <strong>{len(filtered):,}</strong> "
            f"of <strong>{len(detailed):,}</strong> issues</p>",
            unsafe_allow_html=True,
        )

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True,
            column_config={
                "transaction_id": st.column_config.TextColumn("Transaction ID", width="medium"),
                "issue_type": st.column_config.TextColumn("Issue Type", width="medium"),
                "description": st.column_config.TextColumn("Description", width="large"),
                "severity": st.column_config.TextColumn("Severity", width="small"),
            },
        )
    else:
        st.success("✅ No issues found — all records reconcile perfectly!")

    # ── Downloads ────────────────────────────────────────────────────────

    st.markdown("---")
    section_header("Download Reports", "💾")

    dl1, dl2, dl3, dl4 = st.columns(4)

    with dl1:
        st.download_button(
            label="📥 Detailed Report",
            data=detailed.to_csv(index=False),
            file_name="detailed_report.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with dl2:
        st.download_button(
            label="📥 Summary Report",
            data=build_summary_csv(summary),
            file_name="summary_report.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with dl3:
        st.download_button(
            label="📥 Transactions",
            data=st.session_state["transactions"].to_csv(index=False),
            file_name="transactions.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with dl4:
        st.download_button(
            label="📥 Settlements",
            data=st.session_state["settlements"].to_csv(index=False),
            file_name="settlements.csv",
            mime="text/csv",
            use_container_width=True,
        )

elif "transactions" in st.session_state:
    st.markdown("---")
    st.info("👈 Click **Run Reconciliation** in the sidebar to analyze the data.")
