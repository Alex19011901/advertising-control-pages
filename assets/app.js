const DATA_URL = "data/dashboard.json";
const RANGE_LABELS = {
  today: "Сегодня",
  yesterday: "Вчера",
  "7": "7 дней",
  "30": "30 дней",
  all: "Весь период"
};

let dashboard = null;
let activeRange = "30";

const rub = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  maximumFractionDigits: 0
});
const num = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const dec = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

function byId(id) {
  return document.getElementById(id);
}

function fmtNumber(value) {
  return value === null || value === undefined ? "Нет данных" : num.format(value);
}

function fmtDecimal(value, suffix = "") {
  return value === null || value === undefined ? "Нет данных" : `${dec.format(value)}${suffix}`;
}

function fmtMoney(value) {
  return value === null || value === undefined ? "Нет данных" : rub.format(value);
}

function fmtDate(value) {
  if (!value) return "Нет данных";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function statusClass(status) {
  if (status === "ok") return "ok";
  if (status === "missing_secret") return "missing";
  if (status === "api_access_pending" || status === "not_checked") return "pending";
  return "error";
}

function statusLabel(source) {
  if (!source) return "Нет данных";
  const labels = {
    ok: "OK",
    not_checked: "API access pending",
    api_access_pending: "API access pending",
    missing_secret: "Нет секрета",
    request_error: "Ошибка запроса",
    direct_unavailable: "API недоступен",
    lead_unavailable: "JSON недоступен",
    no_data: "Нет данных"
  };
  return labels[source.status] || source.status || "Нет данных";
}

function setStatus() {
  const direct = dashboard?.data_sources?.direct || {};
  const leads = dashboard?.data_sources?.lead_control || {};
  byId("directStatus").className = `pill ${statusClass(direct.status)}`;
  byId("directStatus").textContent = `Яндекс Директ: ${statusLabel(direct)}`;
  byId("leadStatus").className = `pill ${statusClass(leads.status)}`;
  byId("leadStatus").textContent = `Lead Control: ${statusLabel(leads)}`;
  byId("updatedAt").textContent = `Обновлено: ${fmtDate(dashboard?.generated_at)}`;
  byId("directMessage").textContent = direct.message || "Нет данных";
}

function setKpiValue(id, value, formatter, extraClass = "") {
  const el = byId(id);
  el.textContent = formatter(value);
  el.className = `value ${value === null || value === undefined ? "empty" : extraClass}`.trim();
}

function currentLeadRange() {
  return dashboard?.lead_control?.ranges?.[activeRange] || {};
}

function mergedKpi() {
  const base = { ...(dashboard?.kpi || {}) };
  const leads = currentLeadRange();
  base.real_leads = leads.real_leads ?? base.real_leads ?? null;
  if (base.cost !== null && base.cost !== undefined && base.real_leads) {
    base.fact_cpl = base.cost / base.real_leads;
  } else {
    base.fact_cpl = null;
  }
  if (base.cost !== null && base.cost !== undefined && base.quality_leads) {
    base.quality_cpl = base.cost / base.quality_leads;
  } else {
    base.quality_cpl = null;
  }
  return base;
}

function renderKpis() {
  const kpi = mergedKpi();
  setKpiValue("kpiCost", kpi.cost, fmtMoney);
  setKpiValue("kpiImpressions", kpi.impressions, fmtNumber);
  setKpiValue("kpiClicks", kpi.clicks, fmtNumber);
  setKpiValue("kpiCtr", kpi.ctr, (v) => fmtDecimal(v, "%"));
  setKpiValue("kpiCpc", kpi.cpc, fmtMoney);
  setKpiValue("kpiDirectConversions", kpi.direct_conversions, fmtDecimal);
  setKpiValue("kpiRealLeads", kpi.real_leads, fmtNumber, "good");
  setKpiValue("kpiFactCpl", kpi.fact_cpl, fmtMoney);
  setKpiValue("kpiQualityLeads", kpi.quality_leads, fmtNumber);
  setKpiValue("kpiQualityCpl", kpi.quality_cpl, fmtMoney);
  setKpiValue("kpiSales", kpi.sales_result, fmtNumber);
  setKpiValue("kpiRoas", kpi.roas, (v) => fmtDecimal(v, "x"));
}

function renderLeadSummary() {
  const range = currentLeadRange();
  const status = range.status || {};
  byId("leadRangeName").textContent = RANGE_LABELS[activeRange] || activeRange;
  byId("leadPeriod").textContent = range.start && range.end ? `${range.start} - ${range.end}` : "Нет данных";
  byId("leadTotal").textContent = fmtNumber(range.real_leads ?? null);
  byId("leadOk").textContent = fmtNumber(status.OK ?? null);
  byId("leadLate").textContent = fmtNumber(status.LATE_CRM ?? null);
  byId("leadPending").textContent = fmtNumber(status.PENDING ?? null);
  renderBars("leadEvents", range.event || {});
  renderBars("leadSources", range.source || {});
}

function renderBars(id, values) {
  const entries = Object.entries(values || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!entries.length) {
    byId(id).innerHTML = `<div class="empty-state">Нет данных</div>`;
    return;
  }
  const max = Math.max(...entries.map((entry) => entry[1]), 1);
  byId(id).innerHTML = entries.map(([name, value]) => `
    <div class="bar-row">
      <div title="${escapeHtml(name)}">${escapeHtml(name)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(3, value / max * 100)}%"></div></div>
      <b>${fmtNumber(value)}</b>
    </div>
  `).join("");
}

function renderBreakdown() {
  const rows = dashboard?.direct?.breakdown || [];
  if (!rows.length) {
    byId("breakdownBody").innerHTML = "";
    byId("breakdownEmpty").style.display = "grid";
    return;
  }
  byId("breakdownEmpty").style.display = "none";
  byId("breakdownBody").innerHTML = rows.slice(0, 120).map((row) => `
    <tr>
      <td>${escapeHtml(row.direction || "Без направления")}</td>
      <td>${escapeHtml(row.campaign || "Нет данных")}</td>
      <td>${escapeHtml(row.group || "Нет данных")}</td>
      <td>${escapeHtml(row.ad_or_query || "Нет данных")}</td>
      <td>${fmtMoney(row.cost)}</td>
      <td>${fmtNumber(row.impressions)}</td>
      <td>${fmtNumber(row.clicks)}</td>
      <td>${fmtDecimal(row.ctr, "%")}</td>
      <td>${fmtMoney(row.cpc)}</td>
      <td>${fmtDecimal(row.direct_conversions)}</td>
      <td>${row.real_leads === null || row.real_leads === undefined ? "Нет данных" : fmtNumber(row.real_leads)}</td>
      <td>${row.fact_cpl === null || row.fact_cpl === undefined ? "Нет данных" : fmtMoney(row.fact_cpl)}</td>
    </tr>
  `).join("");
}

function renderDirectSummary() {
  const totals = dashboard?.direct?.totals || {};
  byId("directRows").textContent = fmtNumber(dashboard?.direct?.row_count ?? null);
  byId("directCost").textContent = fmtMoney(totals.cost ?? null);
  byId("directClicks").textContent = fmtNumber(totals.clicks ?? null);
  byId("directConversions").textContent = fmtDecimal(totals.direct_conversions ?? null);
}

function bindRanges() {
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      activeRange = button.dataset.range;
      document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderKpis();
      renderLeadSummary();
    });
  });
}

function render() {
  setStatus();
  renderKpis();
  renderLeadSummary();
  renderDirectSummary();
  renderBreakdown();
}

async function boot() {
  bindRanges();
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`dashboard_${response.status}`);
    dashboard = await response.json();
    render();
  } catch (error) {
    dashboard = {
      generated_at: null,
      data_sources: {
        direct: { status: "no_data", message: "Нет данных" },
        lead_control: { status: "no_data", message: "Нет данных" }
      },
      kpi: {},
      direct: { breakdown: [] },
      lead_control: { ranges: {} }
    };
    render();
  }
}

boot();
