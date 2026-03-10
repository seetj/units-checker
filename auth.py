import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import io

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ABA Weekly Units Checker",
    page_icon="🧩",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;600;700&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background-color: #0f1117; color: #e8eaf0; }
h1, h2, h3 { font-family: 'DM Mono', monospace !important; letter-spacing: -0.5px; }
.main-title {
    font-family: 'DM Mono', monospace; font-size: 2rem; color: #7ee8a2;
    border-bottom: 2px solid #7ee8a2; padding-bottom: 8px; margin-bottom: 4px;
}
.subtitle { color: #888; font-size: 0.9rem; margin-bottom: 32px; font-family: 'DM Mono', monospace; }
.metric-card {
    background: #1a1d27; border: 1px solid #2a2d3a;
    border-radius: 10px; padding: 20px; margin: 8px 0;
}
.exceeded  { border-left: 4px solid #ff6b6b; }
.within    { border-left: 4px solid #7ee8a2; }
.warning   { border-left: 4px solid #ffd93d; }
.upload-label {
    font-family: 'DM Mono', monospace; font-size: 0.75rem; color: #7ee8a2;
    text-transform: uppercase; letter-spacing: 2px; margin-bottom: 6px;
}
.badge-exceeded {
    background: #ff6b6b22; color: #ff6b6b; border: 1px solid #ff6b6b;
    padding: 2px 10px; border-radius: 20px; font-size: 0.75rem;
    font-family: 'DM Mono', monospace; font-weight: 600;
}
.badge-within {
    background: #7ee8a222; color: #7ee8a2; border: 1px solid #7ee8a2;
    padding: 2px 10px; border-radius: 20px; font-size: 0.75rem;
    font-family: 'DM Mono', monospace; font-weight: 600;
}
.badge-warning {
    background: #ffd93d22; color: #ffd93d; border: 1px solid #ffd93d;
    padding: 2px 10px; border-radius: 20px; font-size: 0.75rem;
    font-family: 'DM Mono', monospace; font-weight: 600;
}
hr { border-color: #2a2d3a; }
.streamlit-expanderHeader {
    font-family: 'DM Mono', monospace !important; font-size: 0.85rem !important; color: #aaa !important;
}
.section-header {
    font-family: 'DM Mono', monospace; font-size: 0.7rem; color: #555;
    text-transform: uppercase; letter-spacing: 3px; margin: 24px 0 12px 0;
}
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">🧩 ABA Weekly Units Checker</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Zoho CRM  ×  AlohaABA  →  Weekly Units Utilization Report</div>', unsafe_allow_html=True)

# ── Helper functions ──────────────────────────────────────────────────────────

def parse_date_col(series):
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
        try:
            return pd.to_datetime(series, format=fmt)
        except Exception:
            pass
    return pd.to_datetime(series, infer_datetime_format=True, errors="coerce")


def normalize_id(series):
    return series.astype(str).str.strip().str.upper()


def compute_auth_window(reassessment_date):
    """start = reassessment - 6 months, end = start + 180 days"""
    start_dt = reassessment_date - relativedelta(months=6)
    end_dt   = start_dt + timedelta(days=180)
    return start_dt, end_dt


def week_monday(d):
    if isinstance(d, pd.Timestamp):
        d = d.date()
    return d - timedelta(days=d.weekday())


def build_weekly_breakdown(client_aloha, units_col, date_col, recommended_units, start_d, end_d):
    """One row per Mon–Sun week inside the auth window."""
    if client_aloha.empty:
        return pd.DataFrame()

    rows = []
    week_start = week_monday(start_d)
    final_week = week_monday(end_d)

    while week_start <= final_week:
        week_end        = week_start + timedelta(days=6)
        effective_start = max(week_start, start_d)
        effective_end   = min(week_end,   end_d)

        mask = (
            (client_aloha[date_col].dt.date >= effective_start) &
            (client_aloha[date_col].dt.date <= effective_end)
        )
        units    = client_aloha.loc[mask, units_col].sum()
        over_by  = max(0.0, units - recommended_units)

        if units > recommended_units:
            status = "OVER"
        elif recommended_units > 0 and units >= recommended_units * 0.8:
            status = "AT LIMIT"
        else:
            status = "OK"

        rows.append({
            "Week Start":    week_start.strftime("%m/%d/%Y"),
            "Week End":      week_end.strftime("%m/%d/%Y"),
            "Units Used":    int(units),
            "Rec. Units/wk": int(recommended_units),
            "Over By":       int(over_by) if over_by > 0 else "—",
            "Weekly Status": status,
        })
        week_start += timedelta(weeks=1)

    return pd.DataFrame(rows)


def build_report(zoho_df, aloha_df):
    # ── Detect Zoho columns ──────────────────────────────────────────────────
    zoho_id_col = next(
        (c for c in zoho_df.columns if "medicaid" in c.lower() and "id" in c.lower()),
        next((c for c in zoho_df.columns if "medicaid" in c.lower()), None)
    )
    reassess_col = next(
        (c for c in zoho_df.columns if "reassess" in c.lower() and "date" in c.lower()),
        next((c for c in zoho_df.columns if "reassess" in c.lower()), None)
    )
    rec_hours_col = next(
        (c for c in zoho_df.columns if c.lower() == "reccomended_hours_of_treatment"),
        next((c for c in zoho_df.columns if "rec" in c.lower() and "hour" in c.lower()),
        next((c for c in zoho_df.columns if "recommend" in c.lower()), None))
    )
    client_name_col = next(
        (c for c in zoho_df.columns if "name" in c.lower() or "client" in c.lower()), None
    )

    missing_zoho = [
        label for label, col in [
            ("Medicaid ID",                    zoho_id_col),
            ("Reassessment Date",              reassess_col),
            ("Reccomended_Hours_of_Treatment", rec_hours_col),
        ] if col is None
    ]
    if missing_zoho:
        st.error(
            f"Could not find required Zoho columns: **{', '.join(missing_zoho)}**\n\n"
            f"Detected columns: `{list(zoho_df.columns)}`"
        )
        return None

    # ── Detect Aloha columns ─────────────────────────────────────────────────
    aloha_id_col = next(
        (c for c in aloha_df.columns if "insured" in c.lower() and "id" in c.lower()),
        next((c for c in aloha_df.columns if "insured" in c.lower()), None)
    )
    completed_col = next((c for c in aloha_df.columns if "completed" in c.lower()), None)
    service_col   = next(
        (c for c in aloha_df.columns if "service" in c.lower() and "name" in c.lower()),
        next((c for c in aloha_df.columns if "service" in c.lower()), None)
    )
    units_col = next(
        (c for c in aloha_df.columns if c.lower() == "units"),
        next((c for c in aloha_df.columns if "unit" in c.lower()), None)
    )
    date_of_service_col = next(
        (c for c in aloha_df.columns if "date" in c.lower() and "service" in c.lower()),
        next((c for c in aloha_df.columns if "date" in c.lower()), None)
    )

    missing_aloha = [
        label for label, col in [
            ("Insured ID",      aloha_id_col),
            ("Completed",       completed_col),
            ("Service Name",    service_col),
            ("Units",           units_col),
            ("Date of Service", date_of_service_col),
        ] if col is None
    ]
    if missing_aloha:
        st.error(
            f"Could not find required Aloha columns: **{', '.join(missing_aloha)}**\n\n"
            f"Detected columns: `{list(aloha_df.columns)}`"
        )
        return None

    # ── Clean & parse ────────────────────────────────────────────────────────
    zoho_df  = zoho_df.copy()
    aloha_df = aloha_df.copy()

    zoho_df[zoho_id_col]   = normalize_id(zoho_df[zoho_id_col])
    zoho_df[reassess_col]  = parse_date_col(zoho_df[reassess_col])
    zoho_df[rec_hours_col] = pd.to_numeric(zoho_df[rec_hours_col], errors="coerce") * 4  # convert hours → units (1 hr = 4 units)

    aloha_df[aloha_id_col]        = normalize_id(aloha_df[aloha_id_col])
    aloha_df[date_of_service_col] = parse_date_col(aloha_df[date_of_service_col])
    aloha_df[units_col] = pd.to_numeric(aloha_df[units_col], errors="coerce")

    # Filter: Completed = Yes AND Service Name = Direct Service BT
    aloha_filtered = aloha_df[
        (aloha_df[completed_col].astype(str).str.strip().str.upper() == "YES") &
        (aloha_df[service_col].astype(str).str.strip().str.upper()   == "DIRECT SERVICE BT")
    ].copy()

    # ── Per-client loop ──────────────────────────────────────────────────────
    results = []
    today   = datetime.today().date()

    for _, row in zoho_df.iterrows():
        medicaid_id = row[zoho_id_col]
        reassess_dt = row[reassess_col]
        rec_units   = row[rec_hours_col]  # already converted to units (×4)
        client_name = row[client_name_col] if client_name_col else "—"

        if pd.isna(reassess_dt) or pd.isna(rec_units):
            results.append({
                "Client Name":           client_name,
                "Medicaid / Insured ID": medicaid_id,
                "Auth Period Start":     "N/A",
                "Auth Period End":       "N/A",
                "Recommended Wkly Units": rec_units,
                "Total Units Used":       "N/A",
                "Weekly Overage Weeks":  "N/A",
                "Sessions Counted":      "N/A",
                "Weekly Status":         "MISSING DATA",
                "_status_css":           "warning",
                "_weekly_df":            pd.DataFrame(),
            })
            continue

        start_dt, end_dt = compute_auth_window(reassess_dt)
        start_d = start_dt.date() if hasattr(start_dt, "date") else start_dt
        end_d   = end_dt.date()   if hasattr(end_dt,   "date") else end_dt

        client_aloha = aloha_filtered[
            (aloha_filtered[aloha_id_col] == medicaid_id) &
            (aloha_filtered[date_of_service_col].dt.date >= start_d) &
            (aloha_filtered[date_of_service_col].dt.date <= end_d)
        ]

        total_units_used = client_aloha[units_col].sum()

        # Weekly breakdown
        weekly_df    = build_weekly_breakdown(
            client_aloha, units_col, date_of_service_col,
            rec_units, start_d, end_d
        )
        n_over_weeks = int((weekly_df["Weekly Status"] == "OVER").sum()) if not weekly_df.empty else 0
        n_at_limit   = int((weekly_df["Weekly Status"] == "AT LIMIT").sum()) if not weekly_df.empty else 0

        if n_over_weeks > 0:
            weekly_status = "WEEKS OVER LIMIT"
            status_css    = "exceeded"
        elif n_at_limit > 0:
            weekly_status = "AT LIMIT"
            status_css    = "warning"
        else:
            weekly_status = "ALL WEEKS OK"
            status_css    = "within"

        results.append({
            "Client Name":           client_name,
            "Medicaid / Insured ID": medicaid_id,
            "Auth Period Start":     start_d.strftime("%m/%d/%Y"),
            "Auth Period End":       end_d.strftime("%m/%d/%Y"),
            "Recommended Wkly Units": int(rec_units),
            "Total Units Used":       int(total_units_used),
            "Weekly Overage Weeks":  n_over_weeks,
            "Weeks At Limit":        n_at_limit,
            "Sessions Counted":      len(client_aloha),
            "Weekly Status":         weekly_status,
            "_status_css":           status_css,
            "_weekly_df":            weekly_df,
        })

    return results


# ── Render ────────────────────────────────────────────────────────────────────

def render_weekly_table(weekly_df):
    if weekly_df.empty:
        st.caption("No sessions found for this client in the auth window.")
        return

    def color_row(row):
        if row["Weekly Status"] == "OVER":
            c = "#ff6b6b"
        elif row["Weekly Status"] == "AT LIMIT":
            c = "#ffd93d"
        else:
            c = "#7ee8a2"
        return [f"color: {c}" if col in ("Weekly Status", "Over By", "Units Used") else "" for col in row.index]

    st.dataframe(weekly_df.style.apply(color_row, axis=1), use_container_width=True, hide_index=True)


def render_report(results):
    if not results:
        st.warning("No results to display.")
        return

    df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in results])

    # Summary bar
    total        = len(results)
    n_over       = sum(1 for r in results if r["Weekly Status"] == "WEEKS OVER LIMIT")
    n_at_limit   = sum(1 for r in results if r["Weekly Status"] == "AT LIMIT")
    n_ok         = sum(1 for r in results if r["Weekly Status"] == "ALL WEEKS OK")
    n_missing    = sum(1 for r in results if r["Weekly Status"] == "MISSING DATA")

    st.markdown('<div class="section-header">Summary</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Clients",         total)
    c2.metric("🔴 Weeks Over Limit",   n_over)
    c3.metric("🟡 Weeks At Limit",     n_at_limit)
    c4.metric("🟢 All Weeks OK",       n_ok)

    st.markdown("---")

    # Flagged cards
    flagged = [r for r in results if r["Weekly Status"] in ("WEEKS OVER LIMIT", "AT LIMIT")]

    if flagged:
        st.markdown('<div class="section-header">⚠️ Flagged Clients</div>', unsafe_allow_html=True)
        for r in flagged:
            css_class = r["_status_css"]

            if r["Weekly Status"] == "WEEKS OVER LIMIT":
                badge_css  = "exceeded"
                badge_text = f"⚠ {r['Weekly Overage Weeks']} week(s) over recommended"
            else:
                badge_css  = "warning"
                badge_text = f"🟡 {r['Weeks At Limit']} week(s) at limit"

            st.markdown(f"""
            <div class="metric-card {css_class}">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                    <div>
                        <div style="font-family:'DM Mono',monospace; font-size:1rem; font-weight:600; color:#e8eaf0;">
                            {r['Client Name']}
                        </div>
                        <div style="font-family:'DM Mono',monospace; font-size:0.75rem; color:#888;">
                            ID: {r['Medicaid / Insured ID']} &nbsp;·&nbsp; {r['Auth Period Start']} → {r['Auth Period End']}
                        </div>
                    </div>
                    <span class="badge-{badge_css}">{badge_text}</span>
                </div>
                <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:16px;">
                    <div>
                        <div style="font-size:0.62rem; color:#666; text-transform:uppercase; letter-spacing:1px; font-family:'DM Mono',monospace;">Rec. Units/wk</div>
                        <div style="font-size:1.1rem; font-weight:700; color:#e8eaf0; font-family:'DM Mono',monospace;">{r['Recommended Wkly Units']} units</div>
                    </div>
                    <div>
                        <div style="font-size:0.62rem; color:#666; text-transform:uppercase; letter-spacing:1px; font-family:'DM Mono',monospace;">Total Units Used</div>
                        <div style="font-size:1.1rem; font-weight:700; color:#e8eaf0; font-family:'DM Mono',monospace;">{r['Total Units Used']} units</div>
                    </div>
                    <div>
                        <div style="font-size:0.62rem; color:#666; text-transform:uppercase; letter-spacing:1px; font-family:'DM Mono',monospace;">Weeks Over</div>
                        <div style="font-size:1.1rem; font-weight:700; color:#ff6b6b; font-family:'DM Mono',monospace;">{r['Weekly Overage Weeks']}</div>
                    </div>
                    <div>
                        <div style="font-size:0.62rem; color:#666; text-transform:uppercase; letter-spacing:1px; font-family:'DM Mono',monospace;">Sessions</div>
                        <div style="font-size:1.1rem; font-weight:700; color:#aaa; font-family:'DM Mono',monospace;">{r['Sessions Counted']}</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"📅 Weekly breakdown — {r['Client Name']}"):
                render_weekly_table(r["_weekly_df"])

    # Full table
    st.markdown('<div class="section-header">Full Client Report</div>', unsafe_allow_html=True)
    display_cols = [c for c in [
        "Client Name", "Medicaid / Insured ID",
        "Auth Period Start", "Auth Period End",
        "Recommended Wkly Units", "Total Units Used",
        "Weekly Overage Weeks", "Weeks At Limit",
        "Sessions Counted", "Weekly Status",
    ] if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

    # All-clients weekly detail
    with st.expander("📋 View weekly breakdown for all clients"):
        for r in results:
            if r["Weekly Status"] == "MISSING DATA":
                continue
            st.markdown(
                f"**{r['Client Name']}** — `{r['Medicaid / Insured ID']}` "
                f"&nbsp;·&nbsp; Rec. {r['Recommended Wkly Units']} units/wk"
            )
            render_weekly_table(r["_weekly_df"])
            st.markdown("---")

    # CSV download
    csv_buf = io.StringIO()
    df[display_cols].to_csv(csv_buf, index=False)
    st.download_button(
        label="⬇ Download Report CSV",
        data=csv_buf.getvalue().encode(),
        file_name=f"weekly_units_report_{datetime.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📋 Expected Columns")
    st.markdown("**Zoho Export**")
    st.code(
        "Medicaid ID\n"
        "Reassessment Date\n"
        "Reccomended_Hours_of_Treatment\n"
        "Client Name (optional)",
        language="text"
    )
    st.markdown("**AlohaABA Export**")
    st.code(
        "Insured ID\nCompleted\nService Name\nUnits\nDate of Service",
        language="text"
    )
    st.markdown("---")
    st.markdown("**Logic**")
    st.markdown(
        "- Auth window: `Reassessment Date − 6 months` → `+ 180 days`\n"
        "- Filter Aloha: `Completed = Yes` AND `Service Name = Direct Service BT`\n"
        "- Match key: `Medicaid ID` ↔ `Insured ID`\n"
        "- Weeks: **Monday → Sunday**\n\n"
        "**Weekly flags**\n"
        "- 🔴 Over: units that week > recommended (hrs × 4)\n"
        "- 🟡 At Limit: ≥80% of recommended weekly units\n"
        "- 1 unit = 15 mins · 1 hr = 4 units"
    )

# ── Main: uploaders ───────────────────────────────────────────────────────────
st.markdown('<div class="section-header">Upload Data</div>', unsafe_allow_html=True)
col_z, col_a = st.columns(2)

with col_z:
    st.markdown('<div class="upload-label">Zoho CRM Export</div>', unsafe_allow_html=True)
    zoho_file = st.file_uploader("", type=["csv", "xlsx", "xls"], key="zoho",
                                  label_visibility="collapsed")
with col_a:
    st.markdown('<div class="upload-label">AlohaABA Export</div>', unsafe_allow_html=True)
    aloha_file = st.file_uploader("", type=["csv", "xlsx", "xls"], key="aloha",
                                   label_visibility="collapsed")


def read_file(f):
    return pd.read_csv(f) if f.name.endswith(".csv") else pd.read_excel(f)


if zoho_file and aloha_file:
    zoho_df  = read_file(zoho_file)
    aloha_df = read_file(aloha_file)

    with st.expander("🔍 Preview uploaded data"):
        t1, t2 = st.tabs(["Zoho", "AlohaABA"])
        with t1:
            st.dataframe(zoho_df.head(10), use_container_width=True)
        with t2:
            st.dataframe(aloha_df.head(10), use_container_width=True)

    st.markdown("---")
    if st.button("▶ Generate Weekly Report", type="primary"):
        with st.spinner("Analyzing..."):
            results = build_report(zoho_df, aloha_df)
        if results:
            render_report(results)

elif zoho_file or aloha_file:
    st.info("Upload both files to generate the report.")
else:
    st.markdown("""
    <div style="background:#1a1d27; border:1px dashed #2a2d3a; border-radius:10px;
                padding:40px; text-align:center; margin-top:24px;">
        <div style="font-family:'DM Mono',monospace; font-size:1.1rem; color:#555;">
            Upload your Zoho and AlohaABA exports above to get started
        </div>
        <div style="font-family:'DM Mono',monospace; font-size:0.75rem; color:#333; margin-top:8px;">
            Accepts .csv · .xlsx · .xls
        </div>
    </div>
    """, unsafe_allow_html=True)