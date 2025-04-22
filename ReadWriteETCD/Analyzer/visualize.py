from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from io import StringIO
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import etcd3
import json
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from dateutil.parser import parse
import secrets

# --- FastAPI App ---
app = FastAPI(title="ThreatView CVE - Made by Team 1")

# --- etcd Connection ---
etcd = etcd3.client(
    host="10.0.0.11",
    port=2379,
    ca_cert="/opt/cfssl/ca.pem",
    cert_cert="/opt/cfssl/etcd.pem",
    cert_key="/opt/cfssl/etcd-key.pem",
    timeout=10
)

# --- Basic Auth Setup ---
security = HTTPBasic()

VALID_USERS = {
    "admin": "UIT111!!!",
}

def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_password = VALID_USERS.get(credentials.username)
    if not correct_password or not secrets.compare_digest(credentials.password, correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Không có quyền truy cập",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- Helper Functions ---
def load_all_cves():
    cves = []
    for value, metadata in etcd.get_prefix("/vulns/cve/analyzed/"):
        try:
            cves.append(json.loads(value.decode()))
        except:
            continue
    return pd.DataFrame(cves)

def parse_date_safe(date_str):
    try:
        return parse(date_str).date()
    except Exception:
        return None

# --- Web UI ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html data-bs-theme="light">
    <head>
        <title>ThreatView CVE - Made by Team 1</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
        <style>
            .overlay {
                position: fixed;
                top: 0; left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(255, 255, 255, 0.85);
                z-index: 9999;
                display: flex;
                justify-content: center;
                align-items: center;
                transition: opacity 0.6s ease;
            }
            .overlay.hidden {
                opacity: 0;
                pointer-events: none;
            }
            .chart-wrapper {
                opacity: 0;
                transition: opacity 0.6s ease-in-out;
            }
            .chart-wrapper.visible {
                opacity: 1;
            }
            summary {
                cursor: pointer;
                font-weight: bold;
            }
        </style>
        <script>
            let refreshInterval = null;
            function refreshCharts(initial = false) {
                const overlay = document.getElementById("loadingOverlay");
                const wrapper = document.getElementById("chartWrapper");
                overlay.classList.remove("hidden");
                wrapper.classList.remove("visible");
                const now = new Date().getTime();
                let remaining = 4;
                const done = () => {
                    remaining -= 1;
                    if (remaining <= 0) {
                        setTimeout(() => {
                            overlay.classList.add("hidden");
                            wrapper.classList.add("visible");
                        }, 200);
                    }
                };
                const iframes = [
                    document.getElementById('severity_recent'),
                    document.getElementById('severity_distribution'),
                    document.getElementById('cve_trend'),
                    document.getElementById('latest_cves')
                ];
                iframes.forEach(iframe => {
                    iframe.onload = null;
                    iframe.src = iframe.src.split('?')[0] + "?ts=" + now;
                    iframe.onload = done;
                });
                setTimeout(() => {
                    overlay.classList.add("hidden");
                    wrapper.classList.add("visible");
                }, 6000);
            }
            function setAutoRefresh() {
                if (refreshInterval) clearInterval(refreshInterval);
                const val = document.getElementById('refreshInterval').value;
                if (val === "30") {
                    refreshInterval = setInterval(refreshCharts, 30000);
                } else if (val === "60") {
                    refreshInterval = setInterval(refreshCharts, 60000);
                }
            }
            function toggleTheme() {
                const html = document.querySelector('html');
                html.setAttribute('data-bs-theme', html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark');
            }
            window.onload = function () {
                refreshCharts(true);
            };
        </script>
    </head>
    <body class="container py-4 position-relative">
        <h2 class="mb-4">ThreatView CVE - Made by Team 1</h2>
        <div id="loadingOverlay" class="overlay">
            <div class="text-center">
                <div class="spinner-border text-primary mb-3" style="width: 3rem; height: 3rem;" role="status"></div>
                <div class="fw-semibold fs-5">Đang tải biểu đồ...</div>
            </div>
        </div>
        <div class="d-flex justify-content-between align-items-center mb-3">
            <div>
                <button class="btn btn-primary" onclick="refreshCharts()">🔄 Làm mới dữ liệu</button>
                <button class="btn btn-outline-secondary ms-2" onclick="toggleTheme()">🌓 Đổi giao diện</button>
            </div>
            <div>
                <label for="refreshInterval" class="form-label me-2">Tự động làm mới:</label>
                <select id="refreshInterval" class="form-select d-inline-block w-auto" onchange="setAutoRefresh()">
                    <option value="none" selected>Tắt</option>
                    <option value="30">30 giây</option>
                    <option value="60">1 phút</option>
                </select>
            </div>
        </div>
        <div id="chartWrapper" class="chart-wrapper">
            <div class="row g-4">
                <div class="col-md-12">
                    <iframe id="severity_recent" src="/chart/severity_recent" width="100%" height="400" frameborder="0"></iframe>
                </div>
                <div class="col-md-12">
                    <iframe id="severity_distribution" src="/chart/severity_distribution" width="100%" height="400" frameborder="0"></iframe>
                </div>
                <div class="col-md-12">
                    <iframe id="cve_trend" src="/chart/cve_trend" width="100%" height="400" frameborder="0"></iframe>
                </div>
                <div class="col-md-12">
                    <iframe id="latest_cves" src="/chart/latest_cves" width="100%" height="600" frameborder="0"></iframe>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

# --- Chart: Severity Recently ---
@app.get("/chart/severity_recent", response_class=HTMLResponse)
async def severity_recent(
    user: str = Depends(get_current_user),
    from_date: str = Query(default=None),
    to_date: str = Query(default=None),
    date_field: str = Query(default="datePublished")
):
    df = load_all_cves()
    df[date_field] = df[date_field].apply(parse_date_safe)
    df = df.dropna(subset=[date_field])

    if df.empty:
        return "<div class='alert alert-warning'>Không có dữ liệu CVE nào.</div>"

    min_date = df[date_field].min()
    max_date = df[date_field].max()

    try:
        from_dt = parse(from_date).date() if from_date else min_date
        to_dt = parse(to_date).date() if to_date else max_date
    except:
        return "<div class='alert alert-danger'>Lỗi định dạng ngày tháng.</div>"

    df = df[(df[date_field] >= from_dt) & (df[date_field] <= to_dt)]

    from_date_val = from_date if from_date else str(min_date)
    to_date_val = to_date if to_date else str(max_date)

    html_form = f"""
    <form method="get" class="mb-3">
        <label for="from_date">Từ ngày:</label>
        <input type="date" name="from_date" value="{from_date_val}" onchange="this.form.submit()">
        <label for="to_date" style="margin-left:10px;">Đến ngày:</label>
        <input type="date" name="to_date" value="{to_date_val}" onchange="this.form.submit()">
        <label style="margin-left:10px;">Trường ngày:</label>
        <select name="date_field" onchange="this.form.submit()">
    """
    for field in ["datePublished", "dateModified"]:
        selected = "selected" if date_field == field else ""
        html_form += f"<option value='{field}' {selected}>{field}</option>"
    html_form += "</select><hr></form>"

    if df.empty or "baseSeverity" not in df:
        return html_form + f"<div class='alert alert-info'>Không có dữ liệu CVE từ {from_dt} đến {to_dt}.</div>"

    latest_date = df[date_field].max()
    latest_df = df[df[date_field] == latest_date]

    count = latest_df["baseSeverity"].value_counts().reset_index()
    count.columns = ["Severity", "Count"]
    fig = px.bar(count, x="Severity", y="Count",
                 title=f"Thống kê CVE xuất hiện trong ngày gần nhất có dữ liệu: {latest_date}",
                 color="Severity", template="plotly_white",
                 labels={"Severity": "Mức độ", "Count": "Số lượng"})
    html_chart = fig.to_html(full_html=False)

    return f"""
    <div style="background-color: white; padding: 1rem;">
        {html_form}
        {html_chart}
    </div>
    """

# --- Chart: Severity Distribution ---
@app.get("/chart/severity_distribution", response_class=HTMLResponse)
async def severity_distribution(
    user: str = Depends(get_current_user),
    from_date: str = Query(default=None),
    to_date: str = Query(default=None),
    date_field: str = Query(default="dateModified")
):
    df = load_all_cves()
    df[date_field] = df[date_field].apply(parse_date_safe)
    df = df.dropna(subset=[date_field])

    if df.empty:
        return "<div class='alert alert-warning'>Không có dữ liệu CVE nào.</div>"

    min_date = df[date_field].min()
    max_date = df[date_field].max()

    try:
        from_dt = parse(from_date).date() if from_date else min_date
        to_dt = parse(to_date).date() if to_date else max_date
    except:
        return "<div class='alert alert-danger'>Lỗi định dạng ngày tháng.</div>"

    df = df[(df[date_field] >= from_dt) & (df[date_field] <= to_dt)]

    from_date_val = from_date if from_date else str(min_date)
    to_date_val = to_date if to_date else str(max_date)

    html_form = f"""
    <form method="get" class="mb-3">
        <label for="from_date">Từ ngày:</label>
        <input type="date" name="from_date" value="{from_date_val}" onchange="this.form.submit()">
        <label for="to_date" style="margin-left:10px;">Đến ngày:</label>
        <input type="date" name="to_date" value="{to_date_val}" onchange="this.form.submit()">
        <label style="margin-left:10px;">Trường ngày:</label>
        <select name="date_field" onchange="this.form.submit()">
    """
    for field in ["datePublished", "dateModified"]:
        selected = "selected" if date_field == field else ""
        html_form += f"<option value='{field}' {selected}>{field}</option>"
    html_form += "</select><hr></form>"

    if df.empty or "baseSeverity" not in df:
        return html_form + f"<div class='alert alert-info'>Không có dữ liệu CVE từ {from_dt} đến {to_dt}.</div>"

    count = df["baseSeverity"].value_counts().reset_index()
    count.columns = ["Severity", "Count"]
    fig = px.pie(count, names="Severity", values="Count",
                 title=f"Phân bố mức độ nghiêm trọng CVE ({from_dt} → {to_dt})",
                 color_discrete_sequence=px.colors.qualitative.Set3,
                 labels={"Severity": "Mức độ", "Count": "Số lượng"})
    html_chart = fig.to_html(full_html=False)

    return f"""
    <div style="background-color: white; padding: 1rem;">
        {html_form}
        {html_chart}
    </div>
    """

# --- Chart: CVE Trend ---
@app.get("/chart/cve_trend", response_class=HTMLResponse)
async def cve_trend(user: str = Depends(get_current_user)):
    df = load_all_cves()

    # Chuyển đổi ngày an toàn
    df["datePublished"] = df["datePublished"].apply(parse_date_safe)
    df["dateModified"] = df["dateModified"].apply(parse_date_safe)

    df = df.dropna(subset=["datePublished", "dateModified"])

    # Group theo ngày công bố
    pub_trend = df.groupby("datePublished").size().reset_index(name="count")
    pub_trend["type"] = "Công bố"

    # Group theo ngày cập nhật
    mod_trend = df.groupby("dateModified").size().reset_index(name="count")
    mod_trend["type"] = "Cập nhật"

    trend_df = pd.concat([pub_trend.rename(columns={"datePublished": "date"}),
                          mod_trend.rename(columns={"dateModified": "date"})])

    # Vẽ biểu đồ
    fig = px.line(
        trend_df,
        x="date",
        y="count",
        color="type",
        markers=True,
        title="Xu hướng công bố và cập nhật CVE theo thời gian",
        template="plotly_white",
        labels={"date": "Mốc thời gian", "count": "Số lượng CVE", "type": "Loại"}
    )

    return fig.to_html(full_html=False)

# --- Chart: Latest CVEs ---
@app.get("/chart/latest_cves", response_class=HTMLResponse)
async def latest_cves(
    user: str = Depends(get_current_user),
    selected_date: str = Query(default=None, alias="date"),
    top_n: int = Query(default=10, ge=1, le=9999, alias="limit"),
    severity_filter: list[str] = Query(default=["all"], alias="severity"),
    date_field: str = Query(default="datePublished") 
):
    df = load_all_cves()

    df[date_field] = df[date_field].apply(parse_date_safe) 
    df = df.dropna(subset=[date_field]) 

    unique_dates = sorted(df[date_field].unique(), reverse=True) 
    if not unique_dates:
        return "<div class='alert alert-warning'>Không có dữ liệu CVE nào.</div>"

    chosen_date = parse(selected_date).date() if selected_date else unique_dates[0]
    df = df[df[date_field] == chosen_date]             

    if "all" not in [s.lower() for s in severity_filter]:
        df = df[df["baseSeverity"].isin([s.upper() for s in severity_filter])]

    df = df.sort_values("baseScore", ascending=False)

    show_all = top_n not in [10, 20, 50, 100]
    if not show_all:
        df = df.head(top_n)
        title_label = f"Top {top_n}"
    else:
        title_label = "Toàn bộ"

    # Start HTML form
    html_select_form = """
    <style>
    .dropdown-checkbox {
        position: relative;
        display: inline-block;
        margin-left: 10px;
    }
    .dropdown-checkbox-content {
        display: none;
        position: absolute;
        background-color: white !important;
        border: 1px solid #ccc;
        padding: 10px;
        min-width: 180px;
        z-index: 1000;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .dropdown-checkbox:hover .dropdown-checkbox-content {
        display: block;
    }
    </style>

    <form method="get" class="mb-3">
        <label for="date">Chọn ngày:</label>
        <select name="date" onchange="this.form.submit()">
    """
    for d in unique_dates:
        selected_attr = "selected" if d == chosen_date else ""
        html_select_form += f"<option value='{d}' {selected_attr}>{d}</option>"
    html_select_form += "</select>"

    html_select_form += f"""
        <label style="margin-left:10px;">Trường ngày:</label>
        <select name="date_field" onchange="this.form.submit()">
    """
    for field in ["datePublished", "dateModified"]:
        selected = "selected" if field == date_field else ""
        html_select_form += f"<option value='{field}' {selected}>{field}</option>"
    html_select_form += "</select>"

    html_select_form += """
        <label for="limit" style="margin-left: 10px;">Số lượng:</label>
        <select name="limit" onchange="this.form.submit()">
    """
    for limit in [10, 20, 50, 100]:
        selected_attr = "selected" if top_n == limit else ""
        html_select_form += f"<option value='{limit}' {selected_attr}>{limit}</option>"
    if show_all:
        html_select_form += f"<option value='{top_n}' selected>Toàn bộ</option>"
    else:
        html_select_form += "<option value='9999'>Toàn bộ</option>"
    html_select_form += "</select>"

    # Dropdown kiểu tickbox cho severity
    html_select_form += """
        <div class="dropdown-checkbox">
            <button type="button" class="btn btn-outline-secondary btn-sm">Mức độ ▼</button>
            <div class="dropdown-checkbox-content">
    """
    for sev in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        checked = "checked" if sev.lower() in [s.lower() for s in severity_filter] or "all" in [s.lower() for s in severity_filter] else ""
        html_select_form += f"""
            <label style="display:block;">
                <input type="checkbox" name="severity" value="{sev.lower()}" {checked} onchange="this.form.submit()"> {sev}
            </label>
        """
    html_select_form += "</div></div><br><hr>"

    # Export CSV link
    export_query = f"date={chosen_date}&limit={top_n}&date_field={date_field}" + "".join([f"&severity={s}" for s in severity_filter])
    html_select_form += f"""
        <a href="/export/cves?{export_query}" class="btn btn-sm btn-success mb-3">
            ⬇️ <span style="text-decoration: underline;">Tải về CSV</span>
        </a>
    """

    # Trường hợp không có dữ liệu
    if df.empty:
        return html_select_form + f"<div class='alert alert-info'>Không có CVE nào với mức độ đã chọn vào ngày {chosen_date}.</div>"

    # Biểu đồ
    fig = px.bar(df, x="baseScore", y="cveId", orientation='h',
                 title=f"{title_label} CVE ({chosen_date})",
                 color="baseSeverity", template="plotly_white",
                 labels={"cveId": "Mã CVE", "baseScore": "Mức điểm", "baseSeverity": "Mức độ"})
    fig.update_layout(yaxis=dict(autorange="reversed"))
    html_chart = fig.to_html(full_html=False)

    # Danh sách chi tiết
    html_table = "<div class='mt-3'><h5>Danh sách chi tiết:</h5><ul>"
    for _, row in df.iterrows():
        refs = "<br>".join([f"<a href='{ref}' target='_blank'>{ref}</a>" for ref in row.get("references", [])])
        html_table += f"""
        <li>
            <strong>{row['cveId']}</strong> - {row['baseSeverity']} ({row['baseScore']})
            <details><summary>References</summary>{refs}</details>
        </li>
        """
    html_table += "</ul></div>"

    return f"""
    <div style="background-color: white; padding: 1rem;">
        {html_select_form}
        {html_chart}
        {html_table}
    </div>
    """

@app.get("/export/cves")
async def export_csv(
    user: str = Depends(get_current_user),
    selected_date: str = Query(default=None, alias="date"),
    top_n: int = Query(default=10, ge=1, le=9999, alias="limit"),
    severity_filter: list[str] = Query(default=["all"], alias="severity"),
    date_field: str = Query(default="datePublished")
):
    df = load_all_cves()
    df[date_field] = df[date_field].apply(parse_date_safe)
    df = df.dropna(subset=[date_field])

    chosen_date = parse(selected_date).date() if selected_date else datetime.utcnow().date()
    df = df[df[date_field] == chosen_date]

    if "all" not in [s.lower() for s in severity_filter]:
        df = df[df["baseSeverity"].isin([s.upper() for s in severity_filter])]

    df = df.sort_values("baseScore", ascending=False)

    if top_n in [10, 20, 50, 100]:
        df = df.head(top_n)

    output = StringIO()
    df.to_csv(output, index=False)
    output.seek(0)

    filename = f"cves_{date_field}_{chosen_date}.csv"
    return StreamingResponse(output, media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })

# --- Entry Point ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("visualize:app", host="0.0.0.0", port=80, reload=False)

