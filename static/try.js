const compact = new Intl.NumberFormat("it-IT", { notation: "compact", maximumFractionDigits: 1 });
const state = { channels: [] };

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = String(value ?? "");
  return element.innerHTML;
}

function lines(value) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function metric(value, label) {
  return `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`;
}

function rankChart(items, targetId, valueKey, labelKey) {
  const target = document.querySelector(targetId);
  if (!items.length) {
    target.innerHTML = '<p class="empty">Dati insufficienti nel campione.</p>';
    return;
  }
  const max = Math.max(...items.map((item) => Number(item[valueKey]) || 0), 1);
  target.innerHTML = items.map((item) => {
    const value = Number(item[valueKey]) || 0;
    return `<div class="rank-row"><span>${escapeHtml(item[labelKey])}</span><i><b style="width:${value / max * 100}%"></b></i><strong>${value}</strong></div>`;
  }).join("");
}

function channelTimestamp(value) {
  if (!value) return "data n.d.";
  return new Intl.DateTimeFormat("it-IT", { year: "numeric", month: "short" }).format(new Date(value));
}

function renderChannels() {
  const query = document.querySelector("#channel-filter").value.trim().toLowerCase();
  const sort = document.querySelector("#channel-sort").value;
  const channels = state.channels.filter((channel) => channel.title.toLowerCase().includes(query));
  const sorters = {
    match: (a, b) => (b.match === "matched") - (a.match === "matched") || b.observed_videos - a.observed_videos || b.total_views - a.total_views,
    newest: (a, b) => (b.created_at || "").localeCompare(a.created_at || ""),
    views: (a, b) => b.average_views - a.average_views,
    subscribers: (a, b) => b.subscribers - a.subscribers,
    engagement: (a, b) => b.engagement_rate - a.engagement_rate,
  };
  channels.sort(sorters[sort]);
  document.querySelector("#channel-summary").textContent = `${channels.length} canali visualizzati`;
  document.querySelector("#channel-list").innerHTML = channels.length ? channels.map((channel, index) => `
    <article class="channel-row">
      <span>${String(index + 1).padStart(2, "0")}</span>
      <div class="channel-main">
        <a href="https://youtube.com/channel/${encodeURIComponent(channel.channel_id)}" target="_blank" rel="noopener noreferrer">${escapeHtml(channel.title)}</a>
        <small>${escapeHtml(channel.country || "paese n.d.")} · ${channelTimestamp(channel.created_at)} · ${channel.observed_videos} video osservati</small>
        <span class="match-badge">${channel.match === "matched" ? "MATCH QUERY" : "OSSERVATO"}</span>
      </div>
      <div class="channel-cell"><strong>${compact.format(channel.subscribers)}</strong><small>iscritti</small></div>
      <div class="channel-cell"><strong>${compact.format(channel.average_views)}</strong><small>views medie</small></div>
      <div class="channel-cell"><strong>${channel.engagement_rate}%</strong><small>interazioni/views</small></div>
      <div class="channel-cell"><strong>${compact.format(channel.total_views)}</strong><small>views osservate</small></div>
    </article>`).join("") : '<p class="empty">Nessun canale corrisponde al filtro.</p>';
}

function renderResults(data) {
  state.channels = data.channels;
  document.querySelector("#result-title").textContent = data.query;
  document.querySelector("#result-notice").textContent = data.notice;
  document.querySelector("#coverage-strip").innerHTML = [
    `<span><b>${data.coverage.channels}</b> canali osservati</span>`,
    `<span><b>${data.coverage.videos}</b> video nel campione</span>`,
    `<span><b>${data.coverage.estimated_quota_units}</b> unità quota stimate</span>`,
    `<span><b>${data.coverage.truncated ? "Sì" : "No"}</b> campione troncato</span>`,
  ].join("");
  document.querySelector("#metric-grid").innerHTML = [
    metric(compact.format(data.metrics.views), "views pubbliche osservate"),
    metric(compact.format(data.metrics.median_subscribers), "iscritti mediani"),
    metric(compact.format(data.metrics.median_average_views), "views medie mediane"),
    metric(data.metrics.commercial_contents, "contenuti con segnali commerciali"),
  ].join("");
  rankChart(data.terms, "#term-chart", "documents", "name");
  rankChart(data.durations, "#format-chart", "contents", "label");
  renderChannels();
  document.querySelector("#analysis-results").hidden = false;
  document.querySelector("#analysis-results").scrollIntoView({ behavior: "smooth", block: "start" });
}

document.querySelector("#public-analysis-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#analyze-button");
  const progress = document.querySelector("#analysis-progress");
  const error = document.querySelector("#analysis-error");
  button.disabled = true;
  button.textContent = "Analisi in corso...";
  progress.hidden = false;
  error.hidden = true;
  document.querySelector("#analysis-results").hidden = true;
  try {
    const response = await fetch("/api/public/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: document.querySelector("#topic").value,
        region_code: document.querySelector("#region").value,
        language: document.querySelector("#language").value,
        days: Number(document.querySelector("#days").value),
        max_channels: Number(document.querySelector("#max-channels").value),
        channels: lines(document.querySelector("#channels").value),
        videos: lines(document.querySelector("#videos").value),
      }),
    });
    let result = null;
    try { result = await response.json(); } catch (parseError) { result = null; }
    if (!response.ok || !result) throw new Error(result?.detail || "Analisi non disponibile. Riprova più tardi.");
    renderResults(result);
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  } finally {
    progress.hidden = true;
    button.disabled = false;
    button.textContent = "Crea la prima analisi →";
  }
});

document.querySelector("#channel-filter").addEventListener("input", renderChannels);
document.querySelector("#channel-sort").addEventListener("change", renderChannels);
