"""
ABA Weekly Units Checker — Streamlit Cloud Edition
───────────────────────────────────────────────────
Uses st.connection("gsheets", type=GSheetsConnection) — no OAuth flow needed.

Setup:
  1. pip install streamlit pandas openpyxl streamlit-gsheets-connection

  2. In Streamlit Cloud → App Settings → Secrets, add:

        [connections.gsheets]
        spreadsheet = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID"
        type        = "public"

     For a PRIVATE sheet, use a service account instead:
        [connections.gsheets]
        spreadsheet  = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID"
        type         = "service_account"
        project_id   = "..."
        private_key_id   = "..."
        private_key      = "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n"
        client_email     = "...@....iam.gserviceaccount.com"
        client_id        = "..."
        auth_uri         = "https://accounts.google.com/o/oauth2/auth"
        token_uri        = "https://oauth2.googleapis.com/token"

  3. For LOCAL development, create .streamlit/secrets.toml with the same content.

  4. Run:  streamlit run aba_dashboard.py
"""

import io
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="ABA Weekly Units Checker", page_icon="🧩", layout="wide")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background-color: #0f1117; color: #e8eaf0; }
h1,h2,h3 { font-family: 'DM Mono', monospace !important; letter-spacing: -0.5px; }
.main-title {
    font-family: 'DM Mono', monospace; font-size: 2rem; color: #7ee8a2;
    border-bottom: 2px solid #7ee8a2; padding-bottom: 8px; margin-bottom: 4px;
}
.subtitle { color: #888; font-size: 0.9rem; margin-bottom: 32px; font-family: 'DM Mono', monospace; }
.metric-card { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 10px; padding: 20px; margin: 8px 0; }
.exceeded { border-left: 4px solid #ff6b6b; }
.within   { border-left: 4px solid #7ee8a2; }
.warning  { border-left: 4px solid #ffd93d; }
.upload-label {
    font-family: 'DM Mono', monospace; font-size: 0.75rem; color: #7ee8a2;
    text-transform: uppercase; letter-spacing: 2px; margin-bottom: 6px;
}
.badge-exceeded { background:#ff6b6b22;color:#ff6b6b;border:1px solid #ff6b6b;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-family:'DM Mono',monospace;font-weight:600; }
.badge-within   { background:#7ee8a222;color:#7ee8a2;border:1px solid #7ee8a2;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-family:'DM Mono',monospace;font-weight:600; }
.badge-warning  { background:#ffd93d22;color:#ffd93d;border:1px solid #ffd93d;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-family:'DM Mono',monospace;font-weight:600; }
hr { border-color: #2a2d3a; }
.streamlit-expanderHeader { font-family:'DM Mono',monospace !important; font-size:0.85rem !important; color:#aaa !important; }
.section-header { font-family:'DM Mono',monospace; font-size:0.7rem; color:#555; text-transform:uppercase; letter-spacing:3px; margin:24px 0 12px 0; }
.status-ok  { background:#7ee8a211; border:1px solid #7ee8a244; border-radius:8px; padding:10px 16px; font-family:'DM Mono',monospace; font-size:0.8rem; color:#7ee8a2; margin-bottom:12px; }
.status-err { background:#ff6b6b11; border:1px solid #ff6b6b44; border-radius:8px; padding:10px 16px; font-family:'DM Mono',monospace; font-size:0.8rem; color:#ff6b6b; margin-bottom:12px; }
.progress-bar-bg { background:#2a2d3a; border-radius:4px; height:6px; margin-top:6px; overflow:hidden; }
.progress-bar-fill-ok   { background:#7ee8a2; height:6px; border-radius:4px; }
.progress-bar-fill-warn { background:#ffd93d; height:6px; border-radius:4px; }
.progress-bar-fill-over { background:#ff6b6b; height:6px; border-radius:4px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">🧩 ABA Weekly Units Checker</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Google Sheets Client List  ×  AlohaABA  →  Weekly Units Utilization Report</div>', unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_date_col(series):
    for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
        try:
            return pd.to_datetime(series, format=fmt)
        except Exception:
            pass
    return pd.to_datetime(series, infer_datetime_format=True, errors="coerce")


def week_monday(d):
    if isinstance(d, pd.Timestamp):
        d = d.date()
    return d - timedelta(days=d.weekday())


def find_col(df, candidates):
    col_map = {c.strip().lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in col_map:
            return col_map[cand.lower()]
    return None


def _fmt_units(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return int(v)


def _fmt_date(v):
    try:
        if pd.isna(v):
            return "N/A"
    except Exception:
        pass
    if hasattr(v, "strftime"):
        return v.strftime("%m/%d/%Y")
    return str(v)


# ── Core logic ────────────────────────────────────────────────────────────────

def build_weekly_breakdown(client_aloha, units_col, date_col, rec_units_wk, start_d, end_d):
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
        units   = client_aloha.loc[mask, units_col].sum()
        over_by = max(0.0, units - rec_units_wk)
        status  = (
            "OVER"     if units > rec_units_wk else
            "AT LIMIT" if rec_units_wk > 0 and units >= rec_units_wk * 0.8 else
            "OK"
        )
        rows.append({
            "Week Start":    week_start.strftime("%m/%d/%Y"),
            "Week End":      week_end.strftime("%m/%d/%Y"),
            "Units Used":    int(units),
            "Rec. Units/wk": int(rec_units_wk),
            "Over By":       int(over_by) if over_by > 0 else "—",
            "Weekly Status": status,
        })
        week_start += timedelta(weeks=1)
    return pd.DataFrame(rows)


def build_report(sheet_df, aloha_df):
    # ── Sheet columns ─────────────────────────────────────────────────────────
    client_name_col = find_col(sheet_df, ["client name", "client", "name"])
    medicaid_id_col = find_col(sheet_df, ["medicaid id", "medicaid_id", "medicaid"])
    coordinator_col = find_col(sheet_df, ["case coordinator", "coordinator", "case manager"])
    hours_col       = find_col(sheet_df, ["hours per week", "hours/week", "hours_per_week", "rec hours"])
    units_auth_col  = find_col(sheet_df, ["units per auth", "units_per_auth", "auth units", "authorized units"])
    auth_start_col  = find_col(sheet_df, ["auth start", "auth start date", "authorization start", "start date"])
    auth_end_col    = find_col(sheet_df, ["auth end", "auth end date", "authorization end", "end date"])

    missing = [l for l, c in [
        ("Client Name",    client_name_col),
        ("Medicaid ID",    medicaid_id_col),
        ("Hours Per Week", hours_col),
    ] if c is None]
    if missing:
        st.error(
            f"Missing required Google Sheet columns: **{', '.join(missing)}**\n\n"
            f"Columns found: `{list(sheet_df.columns)}`"
        )
        return None

    if auth_start_col is None or auth_end_col is None:
        st.warning(
            "⚠️ **Auth Start** / **Auth End** columns not found — "
            "falling back to first session date + 180 days.\n\n"
            f"Sheet columns: `{list(sheet_df.columns)}`"
        )

    # ── Aloha columns ─────────────────────────────────────────────────────────
    insured_id_col = find_col(aloha_df, ["insured id", "insured_id"])
    completed_col  = find_col(aloha_df, ["completed"])
    service_col    = find_col(aloha_df, ["service name", "service"])
    units_col      = find_col(aloha_df, ["units"])
    dos_col        = find_col(aloha_df, ["date of service","Appt. Date", "dos", "service date", "date_of_service"])
    billed_col     = find_col(aloha_df, ["date billed", "billed date", "date_billed", "billed"])

    missing_a = [l for l, c in [
        ("Insured ID",      insured_id_col),
        ("Completed",       completed_col),
        ("Service Name",    service_col),
        ("Units",           units_col),
        ("Date of Service", dos_col),
        ("Date Billed",     billed_col),
    ] if c is None]
    if missing_a:
        st.error(
            f"Missing Aloha columns: **{', '.join(missing_a)}**\n\n"
            f"Columns found: `{list(aloha_df.columns)}`"
        )
        return None

    # ── Parse ─────────────────────────────────────────────────────────────────
    sheet_df = sheet_df.copy()
    aloha_df = aloha_df.copy()

    sheet_df[hours_col] = pd.to_numeric(sheet_df[hours_col], errors="coerce") * 4  # hrs → units
    sheet_df["_id_key"] = sheet_df[medicaid_id_col].astype(str).str.strip().str.upper()
    if units_auth_col:
        sheet_df[units_auth_col] = pd.to_numeric(sheet_df[units_auth_col], errors="coerce")
    if auth_start_col:
        sheet_df[auth_start_col] = parse_date_col(sheet_df[auth_start_col])
    if auth_end_col:
        sheet_df[auth_end_col]   = parse_date_col(sheet_df[auth_end_col])

    aloha_df[dos_col]    = parse_date_col(aloha_df[dos_col])
    aloha_df[units_col]  = pd.to_numeric(aloha_df[units_col], errors="coerce")
    aloha_df["_id_key"]  = aloha_df[insured_id_col].astype(str).str.strip().str.upper()

    # Filter: Completed=Yes, Direct Service BT, Date Billed not null
    aloha_filtered = aloha_df[
        (aloha_df[completed_col].astype(str).str.strip().str.upper() == "YES") &
        (aloha_df[service_col].astype(str).str.strip().str.upper()   == "DIRECT SERVICE BT") &
        (aloha_df[billed_col].notna())
    ].copy()

    # ── Per-client loop ───────────────────────────────────────────────────────
    results = []

    for _, row in sheet_df.iterrows():
        client_name    = row[client_name_col]
        medicaid_id    = row[medicaid_id_col]
        coordinator    = row[coordinator_col]   if coordinator_col  else "—"
        rec_units_wk   = row[hours_col]
        units_auth     = row[units_auth_col]    if units_auth_col   else None
        id_key         = row["_id_key"]
        auth_start_raw = row[auth_start_col]    if auth_start_col   else pd.NaT
        auth_end_raw   = row[auth_end_col]      if auth_end_col     else pd.NaT

        def _base(extra={}):
            return {
                "Client Name":          client_name,
                "Medicaid ID":          medicaid_id,
                "Case Coordinator":     coordinator,
                "Auth Start":           _fmt_date(auth_start_raw),
                "Auth End":             _fmt_date(auth_end_raw),
                "Rec. Units/wk":        int(rec_units_wk) if not pd.isna(rec_units_wk) else "N/A",
                "Units Per Auth":       _fmt_units(units_auth),
                "Units Used":           "N/A",
                "Units Remaining":      "N/A",
                "Auth Used %":          "N/A",
                "Weekly Overage Weeks": "N/A",
                "Weeks At Limit":       "N/A",
                "Sessions":             "N/A",
                "Weekly Status":        "MISSING DATA",
                "_status_css":          "warning",
                "_weekly_df":           pd.DataFrame(),
                "_units_auth":          units_auth,
                "_units_used":          None,
                "_auth_pct":            None,
                **extra,
            }

        if pd.isna(rec_units_wk):
            results.append(_base())
            continue

        client_aloha = aloha_filtered[aloha_filtered["_id_key"] == id_key].copy()

        if client_aloha.empty:
            results.append(_base({
                "Units Used":           0,
                "Units Remaining":      _fmt_units(units_auth) if units_auth else "N/A",
                "Auth Used %":          "0%",
                "Weekly Overage Weeks": 0,
                "Weeks At Limit":       0,
                "Sessions":             0,
                "Weekly Status":        "NO SESSIONS FOUND",
                "_status_css":          "within",
                "_units_used":          0,
                "_auth_pct":            0,
            }))
            continue

        # Auth window
        if not pd.isna(auth_start_raw) and not pd.isna(auth_end_raw):
            start_d = auth_start_raw.date()
            end_d   = auth_end_raw.date()
        else:
            start_d = client_aloha[dos_col].min().date()
            end_d   = start_d + timedelta(days=179)

        client_aloha = client_aloha[
            (client_aloha[dos_col].dt.date >= start_d) &
            (client_aloha[dos_col].dt.date <= end_d)
        ]
        total_used = int(client_aloha[units_col].sum())

        if units_auth is not None and not pd.isna(units_auth) and units_auth > 0:
            remaining    = int(units_auth) - total_used
            auth_pct     = round(total_used / units_auth * 100, 1)
            auth_pct_str = f"{auth_pct}%"
        else:
            remaining = None; auth_pct = None; auth_pct_str = "N/A"

        weekly_df  = build_weekly_breakdown(client_aloha, units_col, dos_col, rec_units_wk, start_d, end_d)
        n_over     = int((weekly_df["Weekly Status"] == "OVER").sum())     if not weekly_df.empty else 0
        n_at_limit = int((weekly_df["Weekly Status"] == "AT LIMIT").sum()) if not weekly_df.empty else 0

        if n_over > 0:        wk_status = "WEEKS OVER LIMIT"; css = "exceeded"
        elif n_at_limit > 0:  wk_status = "AT LIMIT";          css = "warning"
        else:                  wk_status = "ALL WEEKS OK";      css = "within"

        results.append({
            "Client Name":          client_name,
            "Medicaid ID":          medicaid_id,
            "Case Coordinator":     coordinator,
            "Auth Start":           start_d.strftime("%m/%d/%Y"),
            "Auth End":             end_d.strftime("%m/%d/%Y"),
            "Rec. Units/wk":        int(rec_units_wk),
            "Units Per Auth":       _fmt_units(units_auth),
            "Units Used":           total_used,
            "Units Remaining":      remaining if remaining is not None else "N/A",
            "Auth Used %":          auth_pct_str,
            "Weekly Overage Weeks": n_over,
            "Weeks At Limit":       n_at_limit,
            "Sessions":             len(client_aloha),
            "Weekly Status":        wk_status,
            "_status_css":          css,
            "_weekly_df":           weekly_df,
            "_units_auth":          units_auth,
            "_units_used":          total_used,
            "_auth_pct":            auth_pct,
        })

    return results


# ── Render helpers ────────────────────────────────────────────────────────────

def render_weekly_table(weekly_df):
    if weekly_df.empty:
        st.caption("No sessions found in the auth window.")
        return
    def color_row(row):
        c = {"OVER": "#ff6b6b", "AT LIMIT": "#ffd93d"}.get(row["Weekly Status"], "#7ee8a2")
        return [f"color:{c}" if col in ("Weekly Status", "Over By", "Units Used") else "" for col in row.index]
    st.dataframe(weekly_df.style.apply(color_row, axis=1), use_container_width=True, hide_index=True)


def progress_bar_html(pct, remaining, units_auth):
    if pct is None:
        return ""
    clamped    = min(pct, 100)
    fill_class = "progress-bar-fill-over" if pct >= 100 else ("progress-bar-fill-warn" if pct >= 80 else "progress-bar-fill-ok")
    color      = "#ff6b6b"               if pct >= 100 else ("#ffd93d"               if pct >= 80 else "#7ee8a2")
    rem_str    = f"{remaining:,} units remaining" if isinstance(remaining, int) else "N/A"
    return f"""
    <div style="margin-top:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;
                    font-size:0.65rem;font-family:'DM Mono',monospace;color:#666;margin-bottom:4px;">
            <span>{pct}% of auth budget used &nbsp;({int(units_auth):,} total units)</span>
            <span style="color:{color};font-weight:700;">{rem_str}</span>
        </div>
        <div class="progress-bar-bg"><div class="{fill_class}" style="width:{clamped}%;"></div></div>
    </div>"""


def render_report(results, coordinator_filter="All"):
    if not results:
        st.warning("No results to display.")
        return

    if coordinator_filter != "All":
        results = [r for r in results if r.get("Case Coordinator") == coordinator_filter]
    if not results:
        st.info("No clients found for the selected coordinator.")
        return

    df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in results])

    total        = len(results)
    n_over       = sum(1 for r in results if r["Weekly Status"] == "WEEKS OVER LIMIT")
    n_at_lim     = sum(1 for r in results if r["Weekly Status"] == "AT LIMIT")
    n_ok         = sum(1 for r in results if r["Weekly Status"] == "ALL WEEKS OK")
    n_no_data    = sum(1 for r in results if r["Weekly Status"] in ("MISSING DATA", "NO SESSIONS FOUND"))
    n_budget_low = sum(1 for r in results if r.get("_auth_pct") is not None and r["_auth_pct"] >= 80)

    st.markdown('<div class="section-header">Summary</div>', unsafe_allow_html=True)
    cols = st.columns(6)
    for col, label, val in zip(cols,
        ["Total Clients", "🔴 Weeks Over", "🟡 At Limit", "🟢 All OK", "🟠 Auth ≥80%", "⚪ No Sessions"],
        [total, n_over, n_at_lim, n_ok, n_budget_low, n_no_data],
    ):
        col.metric(label, val)

    st.markdown("---")

    flagged      = [r for r in results if r["Weekly Status"] in ("WEEKS OVER LIMIT", "AT LIMIT")]
    budget_extra = [r for r in results if r not in flagged and r.get("_auth_pct") is not None and r["_auth_pct"] >= 80]
    all_flagged  = flagged + budget_extra

    if all_flagged:
        st.markdown('<div class="section-header">⚠️ Flagged Clients</div>', unsafe_allow_html=True)
        for r in all_flagged:
            css_class = r["_status_css"]
            if r["Weekly Status"] == "WEEKS OVER LIMIT":
                badge_css, badge_text = "exceeded", f"⚠ {r['Weekly Overage Weeks']} week(s) over limit"
            elif r["Weekly Status"] == "AT LIMIT":
                badge_css, badge_text = "warning", f"🟡 {r['Weeks At Limit']} week(s) at limit"
            else:
                badge_css, badge_text, css_class = "warning", f"🟠 Auth {r.get('_auth_pct', '')}% used", "warning"

            remaining   = r.get("Units Remaining", "N/A")
            units_auth  = r.get("_units_auth")
            units_used  = r.get("_units_used", 0)
            auth_pct    = r.get("_auth_pct")
            rem_color   = "#ff6b6b" if isinstance(remaining, int) and remaining < 0 else "#7ee8a2"
            rem_display = f"{remaining:,}" if isinstance(remaining, int) else str(remaining)

            st.markdown(f"""
            <div class="metric-card {css_class}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
                    <div>
                        <div style="font-family:'DM Mono',monospace;font-size:1rem;font-weight:600;color:#e8eaf0;">{r['Client Name']}</div>
                        <div style="font-family:'DM Mono',monospace;font-size:0.72rem;color:#888;margin-top:2px;">
                            ID: {r['Medicaid ID']} &nbsp;·&nbsp; Coordinator: {r['Case Coordinator']} &nbsp;·&nbsp; Auth: {r['Auth Start']} → {r['Auth End']}
                        </div>
                    </div>
                    <span class="badge-{badge_css}">{badge_text}</span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:4px;">
                    <div><div style="font-size:0.59rem;color:#555;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace;">Rec. Units/wk</div>
                         <div style="font-size:1rem;font-weight:700;color:#e8eaf0;font-family:'DM Mono',monospace;">{r['Rec. Units/wk']}</div></div>
                    <div><div style="font-size:0.59rem;color:#555;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace;">Auth Budget</div>
                         <div style="font-size:1rem;font-weight:700;color:#aaa;font-family:'DM Mono',monospace;">{r['Units Per Auth']} units</div></div>
                    <div><div style="font-size:0.59rem;color:#555;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace;">Units Used</div>
                         <div style="font-size:1rem;font-weight:700;color:#e8eaf0;font-family:'DM Mono',monospace;">{units_used:,}</div></div>
                    <div><div style="font-size:0.59rem;color:#555;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace;">Units Remaining</div>
                         <div style="font-size:1rem;font-weight:700;color:{rem_color};font-family:'DM Mono',monospace;">{rem_display}</div></div>
                    <div><div style="font-size:0.59rem;color:#555;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace;">Wks Over Limit</div>
                         <div style="font-size:1rem;font-weight:700;color:#ff6b6b;font-family:'DM Mono',monospace;">{r['Weekly Overage Weeks']}</div></div>
                    <div><div style="font-size:0.59rem;color:#555;text-transform:uppercase;letter-spacing:1px;font-family:'DM Mono',monospace;">Sessions</div>
                         <div style="font-size:1rem;font-weight:700;color:#aaa;font-family:'DM Mono',monospace;">{r['Sessions']}</div></div>
                </div>
                {progress_bar_html(auth_pct, remaining, units_auth) if units_auth else ""}
            </div>""", unsafe_allow_html=True)

            with st.expander(f"📅 Weekly breakdown — {r['Client Name']}"):
                render_weekly_table(r["_weekly_df"])

    st.markdown('<div class="section-header">Full Client Report</div>', unsafe_allow_html=True)
    display_cols = [c for c in [
        "Client Name", "Medicaid ID", "Case Coordinator",
        "Auth Start", "Auth End", "Rec. Units/wk", "Units Per Auth",
        "Units Used", "Units Remaining", "Auth Used %",
        "Weekly Overage Weeks", "Weeks At Limit", "Sessions", "Weekly Status",
    ] if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

    with st.expander("📋 Weekly breakdown — all clients"):
        for r in results:
            if r["Weekly Status"] in ("MISSING DATA", "NO SESSIONS FOUND"):
                continue
            rem     = r.get("Units Remaining", "N/A")
            rem_str = f"· {rem:,} units remaining" if isinstance(rem, int) else ""
            st.markdown(
                f"**{r['Client Name']}** `{r['Medicaid ID']}` — `{r['Case Coordinator']}`"
                f"&nbsp;·&nbsp; {r['Rec. Units/wk']} units/wk"
                f"&nbsp;·&nbsp; {r['Auth Start']} → {r['Auth End']} {rem_str}"
            )
            render_weekly_table(r["_weekly_df"])
            st.markdown("---")

    csv_buf = io.StringIO()
    df[display_cols].to_csv(csv_buf, index=False)
    st.download_button(
        label="⬇ Download Report CSV",
        data=csv_buf.getvalue().encode(),
        file_name=f"aba_units_report_{datetime.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── SIDEBAR ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 📋 Expected Sheet Columns")
    st.code(
        "Client Name        ← required\n"
        "Medicaid ID        ← required (match key)\n"
        "Case Coordinator\n"
        "Hours Per Week     ← required (hrs)\n"
        "Units Per Auth     ← total auth budget (units)\n"
        "Auth Start         ← date\n"
        "Auth End           ← date",
        language="text"
    )
    st.markdown("**AlohaABA Export**")
    st.code(
        "Insured ID         ← required (match key)\n"
        "Completed\n"
        "Service Name\n"
        "Units\n"
        "Date of Service\n"
        "Date Billed",
        language="text"
    )
    st.markdown("---")
    st.markdown("**Units logic**")
    st.markdown(
        "- Hours Per Week × 4 = weekly unit budget\n"
        "- Units Per Auth = total auth budget *(in units)*\n"
        "- Units Remaining = Units Per Auth − Units Used\n"
        "- 1 unit = 15 min · 1 hr = 4 units\n\n"
        "**Flags:** 🔴 weekly over · 🟡 ≥80% weekly · 🟠 auth ≥80% used"
    )
    st.markdown("---")
    st.markdown("**Refresh sheet data**")
    if st.button("🔄 Reload Sheet", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ── LOAD SHEET VIA st.connection ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner="Syncing client roster from Google Sheets…")
def load_sheet_cached(worksheet: str = None) -> pd.DataFrame:
    """
    Load the Google Sheet via st.connection("gsheets").
    Cached for 5 minutes — click 'Reload Sheet' in the sidebar to force refresh.
    """
    conn = st.connection("gsheets", type=GSheetsConnection)
    kwargs = {}
    if worksheet:
        kwargs["worksheet"] = worksheet
    return conn.read(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# ── MAIN ──────────────────────────────────────────════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════

# ── Step 1: Load sheet ────────────────────────────────────────────────────────
st.markdown('<div class="section-header">Step 1 — Client Roster (Google Sheets)</div>', unsafe_allow_html=True)

sheet_df = None

# Check if secrets are configured
secrets_ok = (
    hasattr(st, "secrets") and
    "connections" in st.secrets and
    "gsheets" in st.secrets["connections"]
)

if not secrets_ok:
    st.warning(
        "**Google Sheets connection not configured.**\n\n"
        "Add the following to your Streamlit secrets "
        "*(App Settings → Secrets on Streamlit Cloud, or `.streamlit/secrets.toml` locally)*:\n\n"
        "```toml\n"
        "[connections.gsheets]\n"
        "spreadsheet = \"https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID\"\n"
        "type        = \"public\"\n"
        "```\n\n"
        "For a **private sheet**, use a service account — see the docstring at the top of the file."
    )
else:
    # Optional: let user pick a specific worksheet/tab
    worksheet_name = st.text_input(
        "Worksheet / tab name *(leave blank for first tab)*",
        value="",
        placeholder="e.g. Client Roster",
    )

    try:
        sheet_df = load_sheet_cached(worksheet_name.strip() or None)

        if sheet_df is None and sheet_df.empty:
            st.markdown(
                '<div class="status-err">✗ Sheet loaded but appears empty — check the worksheet name</div>',
                unsafe_allow_html=True,
            )

    except Exception as e:
        st.markdown(
            f'<div class="status-err">✗ Could not load sheet: {e}</div>',
            unsafe_allow_html=True,
        )

# ── Step 2: Upload Aloha ──────────────────────────────────────────────────────
st.markdown('<div class="section-header">Step 2 — Upload AlohaABA Export</div>', unsafe_allow_html=True)
st.markdown('<div class="upload-label">AlohaABA Export (.csv / .xlsx)</div>', unsafe_allow_html=True)
aloha_file = st.file_uploader("", type=["csv", "xlsx", "xls"], key="aloha", label_visibility="collapsed")

aloha_df = None
if aloha_file:
    aloha_df = (
        pd.read_csv(aloha_file) if aloha_file.name.endswith(".csv")
        else pd.read_excel(aloha_file)
    )

# ── Step 3: Generate ──────────────────────────────────────────────────────────
if sheet_df is not None and not sheet_df.empty and aloha_df is not None:
    st.markdown("---")

    coordinator_filter = "All"
    coord_col = find_col(sheet_df, ["case coordinator", "coordinator", "case manager"])
    if coord_col:
        coordinators       = ["All"] + sorted(sheet_df[coord_col].dropna().unique().tolist())
        coordinator_filter = st.selectbox("Filter by Case Coordinator", coordinators)

    if st.button("▶ Generate Report", type="primary"):
        with st.spinner("Analyzing sessions…"):
            results = build_report(sheet_df, aloha_df)
        if results:
            render_report(results, coordinator_filter=coordinator_filter)

elif sheet_df is not None and not sheet_df.empty:
    st.info("Upload the AlohaABA export above to generate the report.")
elif aloha_df is not None:
    st.info("Configure your Google Sheets connection to continue.")