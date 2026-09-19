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
const EXACT_METRIKA_METHODS = new Set([
  "metrika_client_session_exact",
  "metrika_client_session_utm_campaign_exact",
  "metrika_client_session_exact_utm_campaign_exact",
  "metrika_tilda_submit_visit_exact",
  "metrika_tilda_submit_visit_utm_campaign_exact"
]);

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
  if (status === "remote_map_fallback") return "ok";
  if (status === "api_access_pending" || status === "not_checked" || status === "counter_mismatch" || status === "attribution_mismatch") return "pending";
  return "error";
}

function statusLabel(source) {
  if (!source) return "Нет данных";
  const labels = {
    ok: "OK",
    not_checked: "API access pending",
    api_access_pending: "API access pending",
    missing_secret: "Нет секрета",
    remote_map_fallback: "Карта Lead Control",
    request_error: "Ошибка запроса",
    direct_unavailable: "API недоступен",
    lead_unavailable: "JSON недоступен",
    lead_attribution_unavailable: "Атрибуция недоступна",
    counter_mismatch: "Не тот счетчик",
    attribution_mismatch: "Не та атрибуция",
    metrika_unavailable: "Метрика недоступна",
    no_data: "Нет данных"
  };
  return labels[source.status] || source.status || "Нет данных";
}

function setStatus() {
  const direct = dashboard?.data_sources?.direct || {};
  const leads = dashboard?.data_sources?.lead_control || {};
  const attribution = dashboard?.data_sources?.lead_attribution || {};
  const map = attribution?.metrika_attribution_map || {};
  byId("directStatus").className = `pill ${statusClass(direct.status)}`;
  byId("directStatus").textContent = `Яндекс Директ: ${statusLabel(direct)}`;
  byId("leadStatus").className = `pill ${statusClass(leads.status)}`;
  byId("leadStatus").textContent = `Lead Control: ${statusLabel(leads)}`;
  byId("attrStatus").className = `pill ${statusClass(map.status || attribution.status)}`;
  byId("attrStatus").textContent = `Метрика: ${statusLabel(map.status ? map : attribution)}`;
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

function currentDashboardRange() {
  return dashboard?.ranges?.[activeRange] || {};
}

function currentDirectRange() {
  return currentDashboardRange().direct || dashboard?.direct || {};
}

function dateOnly(value) {
  const text = String(value || "").trim();
  return text ? text.slice(0, 10) : "";
}

function currentRangeBounds() {
  const fromDashboard = currentDashboardRange();
  const fromLeads = currentLeadRange();
  return {
    start: fromDashboard.start || fromLeads.start || "",
    end: fromDashboard.end || fromLeads.end || ""
  };
}

function isWithinActiveRange(value) {
  const day = dateOnly(value);
  if (!day) return false;
  const { start, end } = currentRangeBounds();
  if (start && day < start) return false;
  if (end && day > end) return false;
  return true;
}

function currentAttributionRows() {
  const rows = dashboard?.lead_attribution?.leads || [];
  const { start, end } = currentRangeBounds();
  if (!start && !end) return rows;
  return rows.filter((lead) => isWithinActiveRange(lead.created_at));
}

function mergedKpi() {
  const base = { ...(currentDashboardRange().kpi || dashboard?.kpi || {}) };
  const leads = currentLeadRange();
  base.real_leads = leads.real_leads ?? base.real_leads ?? null;
  const summary = currentDirectRange().summary || {};
  base.attributed_leads = base.attributed_leads ?? summary.exact_id_matches_available ?? null;
  if (base.cost !== null && base.cost !== undefined && base.attributed_leads) {
    base.fact_cpl = base.cost / base.attributed_leads;
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
  setKpiValue("kpiAttributedLeads", kpi.attributed_leads, fmtNumber, "good");
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
  const rows = currentDirectRange().breakdown || [];
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
  const direct = currentDirectRange();
  const totals = direct.totals || {};
  byId("directRows").textContent = fmtNumber(direct.row_count ?? null);
  byId("directCost").textContent = fmtMoney(totals.cost ?? null);
  byId("directClicks").textContent = fmtNumber(totals.clicks ?? null);
  byId("directConversions").textContent = fmtDecimal(totals.direct_conversions ?? null);
  renderLinkedSpend();
}

function renderLinkedSpend() {
  const summary = currentDirectRange().linked_spend || {};
  const rows = Array.isArray(summary.rows) ? summary.rows : [];
  byId("linkedRows").textContent = fmtNumber(summary.row_count ?? null);
  byId("linkedLeads").textContent = fmtNumber(summary.leads ?? null);
  byId("linkedCost").textContent = fmtMoney(summary.cost ?? null);
  byId("linkedCpl").textContent = fmtMoney(summary.cpl ?? null);
  if (!rows.length) {
    byId("linkedSpendBody").innerHTML = "";
    byId("linkedSpendEmpty").style.display = "grid";
    return;
  }
  byId("linkedSpendEmpty").style.display = "none";
  byId("linkedSpendBody").innerHTML = rows.slice(0, 12).map((row) => `
    <tr>
      <td>${escapeHtml(row.campaign || "Нет данных")}</td>
      <td>${escapeHtml(row.group || "Нет данных")}</td>
      <td>${escapeHtml(row.ad_id || row.ad_or_query || "Нет данных")}</td>
      <td>${fmtNumber(row.real_leads)}</td>
      <td>${fmtMoney(row.cost)}</td>
      <td>${fmtMoney(row.fact_cpl)}</td>
    </tr>
  `).join("");
}

function methodLabel(value) {
  const labels = {
    direct_url_ids: "ID уже в лиде",
    metrika_client_session_exact: "ClientID + сессия",
    metrika_client_session_utm_campaign_exact: "ClientID + UTM кампания",
    metrika_client_session_exact_utm_campaign_exact: "ClientID + UTM кампания",
    metrika_tilda_submit_visit_exact: "Tilda submit + visitID",
    metrika_tilda_submit_visit_utm_campaign_exact: "Tilda submit + UTM кампания",
    metrika_client_latest_prior_visit: "Нет точной сессии",
    metrika_client_latest_prior_visit_utm_campaign_exact: "Нет точной сессии + UTM",
    client_session_unmapped_utm_campaign: "Есть визит, нет ID кампании",
    client_session_without_direct_ids: "Есть визит, нет рекламы",
    tilda_submit_events_unavailable: "Нет событий submit в карте",
    tilda_no_submit_time: "Нет времени submit",
    tilda_no_matching_submit_event: "Submit не найден",
    tilda_ambiguous_submit_events: "Несколько submit",
    tilda_submit_visit_not_in_metrika_map: "Submit visitID нет в карте",
    tilda_ambiguous_submit_visits: "Несколько визитов submit",
    callibri_url_ids: "Callibri ID в заявке",
    callibri_phone_time_match: "Callibri звонок + хостес",
    ambiguous_client_sessions: "Неоднозначно",
    client_id_not_in_metrika_map: "ClientID нет в карте Метрики",
    client_id_no_lead_time: "ClientID без времени заявки",
    client_id_no_session_match: "ClientID вне сессии",
    no_client_id: "Нет ClientID",
    unknown: "Не определено"
  };
  return labels[value] || value || "Нет данных";
}

function callibriStatusLabel(value) {
  const labels = {
    matched: "Звонок найден",
    matched_without_ad_ids: "Звонок без рекламы",
    matched_unconfirmed_tracking: "Трекинг не подтверждён",
    no_callibri_phone_match: "Телефона нет в Callibri",
    nearest_call_outside_window: "Звонок вне окна",
    ambiguous_callibri_calls: "Неоднозначно",
    no_phone_or_time: "Нет телефона/времени",
    no_callibri_call: "Звонок не найден",
    not_matched: "Не связано"
  };
  return labels[value] || value || "Нет данных";
}

function isTildaLead(lead) {
  const source = String(lead?.source || "").toLowerCase();
  return source.includes("tilda") || source.includes("тильда");
}

function isHostessLead(lead) {
  return String(lead?.source || "").toLowerCase().includes("заявки хост");
}

function hasMetrikaClientId(lead) {
  return Boolean(lead?.has_metrika_client_id || lead?.metrika_client_id_sha256);
}

function hasAdIds(lead) {
  return Boolean(lead?.ad_id || lead?.group_id || lead?.campaign_id);
}

function isCallibriAttribution(lead) {
  return String(lead?.advertising_id_source || "").startsWith("callibri");
}

function countBy(rows, getter) {
  return rows.reduce((acc, row) => {
    const key = getter(row) || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function latestRows(rows, count = 5) {
  return rows
    .slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
    .slice(0, count);
}

function summarizeTildaRows(rows) {
  const tildaRows = rows.filter(isTildaLead);
  const withClient = tildaRows.filter(hasMetrikaClientId).length;
  const metrikaMatched = tildaRows.filter((lead) => EXACT_METRIKA_METHODS.has(lead.attribution_method)).length;
  const methods = countBy(tildaRows, (lead) => lead.attribution_method);
  return {
    total: tildaRows.length,
    with_client_id: withClient,
    without_client_id: tildaRows.length - withClient,
    metrika_matched: metrikaMatched,
    with_client_id_unmatched: Math.max(0, withClient - metrikaMatched),
    client_id_not_in_metrika_map: methods.client_id_not_in_metrika_map || 0,
    client_id_no_session_match: methods.client_id_no_session_match || 0,
    ambiguous_client_sessions: methods.ambiguous_client_sessions || 0,
    method_counts: methods,
    latest: latestRows(tildaRows).map((lead) => ({
      lead_id: lead.lead_id,
      created_at: lead.created_at,
      source: lead.source,
      has_metrika_client_id: hasMetrikaClientId(lead),
      attribution_method: lead.attribution_method
    }))
  };
}

function summarizeHostessRows(rows) {
  const hostessRows = rows.filter(isHostessLead);
  const statuses = countBy(hostessRows, (lead) => lead.callibri_match_status || "not_matched");
  return {
    total: hostessRows.length,
    with_ad_ids: hostessRows.filter(hasAdIds).length,
    without_ad_ids: hostessRows.filter((lead) => !hasAdIds(lead)).length,
    with_callibri: hostessRows.filter(isCallibriAttribution).length,
    callibri_phone_not_found: statuses.no_callibri_phone_match || 0,
    callibri_ambiguous: statuses.ambiguous_callibri_calls || 0,
    match_status_counts: statuses,
    latest: latestRows(hostessRows).map((lead) => ({
      lead_id: lead.lead_id,
      created_at: lead.created_at,
      source: lead.source,
      has_ad_ids: hasAdIds(lead),
      advertising_id_source: lead.advertising_id_source || "",
      attribution_method: lead.attribution_method || "",
      callibri_match_status: lead.callibri_match_status || "",
      callibri_candidate_count: lead.callibri_candidate_count
    }))
  };
}

function summarizeAttributionRows(rows) {
  return {
    leads_total: rows.length,
    leads_with_metrika_client_id: rows.filter(hasMetrikaClientId).length,
    matched: rows.filter((lead) => EXACT_METRIKA_METHODS.has(lead.attribution_method)).length,
    method_counts: countBy(rows, (lead) => lead.attribution_method),
    tilda_client_id: summarizeTildaRows(rows),
    hostess_calls: summarizeHostessRows(rows)
  };
}

function renderAttributionSummary() {
  const source = dashboard?.data_sources?.lead_attribution || {};
  const map = source?.metrika_attribution_map || {};
  const rows = currentAttributionRows();
  const diagnostics = summarizeAttributionRows(rows);
  const methods = diagnostics.method_counts || {};
  const period = map.date1 && map.date2 ? `${map.date1} - ${map.date2}` : "Нет данных";
  const counter = map.counter_id ? `${map.counter_id}` : "Нет данных";
  const target = map.target_counter_id ? ` / цель ${map.target_counter_id}` : "";

  byId("attrLeadsTotal").textContent = fmtNumber(diagnostics.leads_total ?? source.lead_count ?? null);
  byId("attrLeadsClient").textContent = fmtNumber(diagnostics.leads_with_metrika_client_id ?? null);
  byId("attrMapRows").textContent = fmtNumber(map.mapped_rows ?? source?.metrika_attribution_diagnostics?.metrika_rows ?? null);
  byId("attrMatches").textContent = fmtNumber(diagnostics.matched ?? null);
  byId("attrCounter").textContent = `${counter}${target}`;
  byId("attrPeriod").textContent = period;
  byId("attrMessage").textContent = map.message || source.message || "Атрибуция строится по ClientID из Lead Control и визитам Метрики.";

  const entries = Object.entries(methods).sort((a, b) => b[1] - a[1]);
  byId("attrMethods").innerHTML = entries.length ? entries.map(([name, value]) => `
    <div class="method-item">
      <span>${escapeHtml(methodLabel(name))}</span>
      <b>${fmtNumber(value)}</b>
    </div>
  `).join("") : `<div class="empty-state">Нет данных</div>`;

  renderTildaClientIdSummary(diagnostics.tilda_client_id || {});
  renderHostessCallSummary(diagnostics.hostess_calls || {});
}

function renderTildaClientIdSummary(summary) {
  const latest = Array.isArray(summary.latest) ? summary.latest[0] : null;
  const methods = summary.method_counts || {};
  const metrikaMatched = summary.metrika_matched ?? methods.metrika_client_session_exact ?? null;
  byId("tildaTotal").textContent = fmtNumber(summary.total ?? null);
  byId("tildaWithClient").textContent = fmtNumber(summary.with_client_id ?? null);
  byId("tildaMetrikaMatched").textContent = fmtNumber(metrikaMatched);
  byId("tildaWithoutClient").textContent = fmtNumber(summary.without_client_id ?? null);
  byId("tildaToday").textContent = fmtRatio(summary.with_client_id, summary.total);
  byId("tilda7Days").textContent = fmtRatio(metrikaMatched, summary.with_client_id);
  byId("tildaClientUnmatched").textContent = fmtNumber(summary.with_client_id_unmatched ?? null);
  byId("tildaNotInMap").textContent = fmtNumber(summary.client_id_not_in_metrika_map ?? methods.client_id_not_in_metrika_map ?? null);
  byId("tildaNoSession").textContent = fmtNumber(
    (summary.client_id_no_session_match ?? methods.client_id_no_session_match ?? 0)
      + (summary.ambiguous_client_sessions ?? methods.ambiguous_client_sessions ?? 0)
  );
  byId("tildaLatest").textContent = latest
    ? `Последняя Tilda: ${fmtDate(latest.created_at)} · ClientID ${latest.has_metrika_client_id ? "есть" : "нет"} · ${methodLabel(latest.attribution_method)}`
    : "Нет Tilda-заявок в текущем export.";
  const entries = Object.entries(methods).sort((a, b) => b[1] - a[1]);
  byId("tildaStatus").innerHTML = entries.length ? entries.map(([name, value]) => `
    <div class="method-item">
      <span>${escapeHtml(methodLabel(name))}</span>
      <b>${fmtNumber(value)}</b>
    </div>
  `).join("") : `<div class="empty-state">Нет данных</div>`;
}

function fmtRatio(numerator, denominator) {
  if (numerator === null || numerator === undefined || denominator === null || denominator === undefined) return "Нет данных";
  return `${fmtNumber(numerator)} / ${fmtNumber(denominator)}`;
}

function renderHostessCallSummary(summary) {
  const latest = Array.isArray(summary.latest) ? summary.latest[0] : null;
  const statuses = summary.match_status_counts || {};
  byId("hostessTotal").textContent = fmtNumber(summary.total ?? null);
  byId("hostessToday").textContent = fmtNumber(summary.with_callibri ?? null);
  byId("hostess7Days").textContent = fmtNumber(summary.without_ad_ids ?? null);
  byId("hostessWithAds").textContent = fmtNumber(summary.with_ad_ids ?? null);
  byId("hostessCallibri").textContent = fmtNumber(summary.with_callibri ?? null);
  byId("hostessPhoneNotFound").textContent = fmtNumber(summary.callibri_phone_not_found ?? statuses.no_callibri_phone_match ?? null);
  byId("hostessAmbiguous").textContent = fmtNumber(summary.callibri_ambiguous ?? statuses.ambiguous_callibri_calls ?? null);
  byId("hostessLatest").textContent = latest
    ? `Последняя хостес: ${fmtDate(latest.created_at)} · ${latest.has_ad_ids ? methodLabel(latest.attribution_method) : callibriStatusLabel(latest.callibri_match_status)}`
    : "Нет заявок хостес в текущем export.";
  const entries = Object.entries(statuses).sort((a, b) => b[1] - a[1]);
  byId("hostessStatus").innerHTML = entries.length ? entries.map(([name, value]) => `
    <div class="method-item">
      <span>${escapeHtml(callibriStatusLabel(name))}</span>
      <b>${fmtNumber(value)}</b>
    </div>
  `).join("") : `<div class="empty-state">Нет данных</div>`;
}

function renderAttributedLeads() {
  const rows = currentAttributionRows();
  const body = byId("leadsBody");
  const empty = byId("leadsEmpty");
  if (!rows.length) {
    body.innerHTML = "";
    empty.style.display = "grid";
    return;
  }
  empty.style.display = "none";
  body.innerHTML = rows.slice().reverse().slice(0, 60).map((lead) => {
    const ids = [
      lead.campaign_id ? `К: ${lead.campaign_id}` : "",
      lead.group_id ? `Г: ${lead.group_id}` : "",
      lead.ad_id ? `О: ${lead.ad_id}` : ""
    ].filter(Boolean).join(" · ");
    const phrase = lead.metrika_phrase_or_condition || lead.utm_term || lead.metrika_utm_campaign || lead.utm_campaign || "";
    return `
      <tr>
        <td>${fmtDate(lead.created_at)}</td>
        <td>${escapeHtml(lead.event_type || "Нет данных")}</td>
        <td>${escapeHtml(lead.source || lead.channel || "Нет данных")}</td>
        <td>${escapeHtml(ids || lead.metrika_campaign_name || "Не связано")}</td>
        <td>${escapeHtml(phrase || "Нет данных")}</td>
        <td>${escapeHtml(methodLabel(lead.attribution_method))}</td>
      </tr>
    `;
  }).join("");
}

function bindRanges() {
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      activeRange = button.dataset.range;
      document.querySelectorAll("[data-range]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderKpis();
      renderLeadSummary();
      renderDirectSummary();
      renderBreakdown();
      renderAttributionSummary();
      renderAttributedLeads();
    });
  });
}

function render() {
  setStatus();
  renderKpis();
  renderLeadSummary();
  renderDirectSummary();
  renderBreakdown();
  renderAttributionSummary();
  renderAttributedLeads();
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
        lead_control: { status: "no_data", message: "Нет данных" },
        lead_attribution: { status: "no_data", message: "Нет данных" }
      },
      kpi: {},
      direct: { breakdown: [] },
      lead_attribution: { leads: [] },
      lead_control: { ranges: {} }
    };
    render();
  }
}

boot();
