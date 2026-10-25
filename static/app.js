const compact = new Intl.NumberFormat("it-IT", { notation: "compact", maximumFractionDigits: 1 });
const weekdays = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];
const state = { projectId: 1, days: 14, niche: "", left: "", right: "", projects: [], youtubeConfigured: false, advDays: 90, advNiche: "", sponsorEntityId: null, sponsorEntities: [], sponsorCompareLeft: "", sponsorCompareRight: "", view: "dashboard", wizardStep: 1, wizardMode: "videos", wizardProjectId: null, wizardNicheId: null, wizardJobId: null, wizardPreview: [], wizardPreviewStats: null, wizardCircles: [], wizardPoolThemes: [], wizardSelected: new Set() };
const handledJobs = new Set();

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = String(value ?? "");
  return element.innerHTML;
}

function metric(value, label, tone = "", kind = "observed") {
  const kindLabels = { observed: "OSSERVATO", calculated: "CALCOLATO", heuristic: "EURISTICO" };
  return `<div class="metric ${tone}"><strong>${value}</strong><span>${label}</span><small class="data-kind ${kind}">${kindLabels[kind]}</small></div>`;
}

function empty(message) {
  return `<p class="empty">${message}</p>`;
}

function renderActivity(activity) {
  const maxHour = Math.max(...activity.hours, 1);
  document.querySelector("#hour-chart").innerHTML = activity.hours.map((value, hour) => `
    <div class="bar-column ${hour === activity.peak_hour ? "is-peak" : ""}" title="${hour}:00 · ${value} commenti">
      <span class="bar-value">${value || ""}</span>
      <i style="height:${Math.max(value / maxHour * 100, 2)}%"></i>
      <small>${hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}</small>
    </div>`).join("");

  const maxDay = Math.max(...activity.days, 1);
  document.querySelector("#day-list").innerHTML = activity.days.map((value, index) => `
    <div class="day-row"><span>${weekdays[index]}</span><i><b style="width:${value / maxDay * 100}%"></b></i><strong>${value}</strong></div>`).join("");
  document.querySelector("#peak-copy").textContent = activity.peak_hour === null
    ? "Dati insufficienti"
    : `Picco osservato tra le ${String(activity.peak_hour).padStart(2, "0")}:00 e le ${String((activity.peak_hour + 1) % 24).padStart(2, "0")}:00`;
}

function renderEvents(events) {
  document.querySelector("#event-list").innerHTML = events.length ? events.map((event, index) => {
    const date = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(event.started_at));
    return `<article class="event-card">
      <div class="event-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="event-main">
        <span class="event-time">${date} · ${escapeHtml(event.content_id)}</span>
        <h3>${escapeHtml(event.content_title)}</h3>
        <div class="evidence-steps">
          <p><span>OSSERVATO</span>${escapeHtml(event.observed)}</p>
          <p><span>CALCOLATO</span>${escapeHtml(event.calculated)}</p>
          <p><span>STIMATO</span>${escapeHtml(event.estimated)}</p>
        </div>
      </div>
      <div class="confidence"><strong>${event.confidence}%</strong><span>forza euristica<br>del segnale</span></div>
    </article>`;
  }).join("") : empty("Nessuna anomalia rilevata nel periodo selezionato.");
}

function renderEvidence(data) {
  document.querySelector("#cluster-list").innerHTML = data.clusters.length ? data.clusters.map((cluster) => `
    <article class="evidence-row">
      <div><q>${escapeHtml(cluster.text)}</q><small>${cluster.authors} autori · ${cluster.contents} contenuti</small></div>
      <strong>${cluster.comments}×</strong>
    </article>`).join("") : empty("Nessun testo ripetuto almeno tre volte.");

  document.querySelector("#author-list").innerHTML = data.authors.length ? data.authors.map((author) => `
    <article class="evidence-row">
      <div><q>${escapeHtml(author.author)}</q><small>${escapeHtml(author.reasons.join(" · "))}</small></div>
      <strong>${author.score}</strong>
    </article>`).join("") : empty("Nessun account supera la soglia di approfondimento.");
}

function renderNiches(niches) {
  const maxComments = Math.max(...niches.items.map((niche) => niche.comments), 1);
  document.querySelector("#niche-grid").innerHTML = niches.items.map((niche) => `
    <article class="niche-card">
      <p class="eyebrow">NICCHIA OSSERVATA</p>
      <h3>${escapeHtml(niche.name)}</h3>
      <div class="niche-stats"><span><strong>${niche.comments}</strong> commenti</span><span><strong>${niche.authors}</strong> autori</span></div>
      <i class="niche-meter" aria-hidden="true"><b style="width:${niche.comments / maxComments * 100}%"></b></i>
      <div class="topic-list">${niche.topics.map((topic) => `<span>${escapeHtml(topic.name)} <b>${topic.count}</b></span>`).join("")}</div>
    </article>`).join("");

  const comparison = niches.comparison;
  document.querySelector("#comparison").innerHTML = comparison ? `
    <div><p class="eyebrow">INCROCIO AGGREGATO</p><h3>${escapeHtml(comparison.left)} <i>×</i> ${escapeHtml(comparison.right)}</h3></div>
    <div class="overlap"><strong>${comparison.audience_overlap}%</strong><span>sovrapposizione<br>del pubblico osservato</span></div>
    <div><span class="comparison-label">ARGOMENTI CONDIVISI</span><p>${comparison.shared_topics.length ? comparison.shared_topics.map(escapeHtml).join(" · ") : "Nessuno nel campione"}</p></div>`
    : empty("Servono almeno due nicchie per effettuare un confronto.");
}

function renderContentLandscape(data) {
  document.querySelector("#content-metrics").innerHTML = [
    metric(data.metrics.contents, `${data.metrics.real_contents} reali · ${data.metrics.demo_contents} demo`, "", "observed"),
    metric(data.metrics.channels, "canali nel campione", "", "calculated"),
    metric(compact.format(data.metrics.views), "visualizzazioni aggregate"),
    metric(compact.format(data.metrics.interactions), "like + commenti", "", "calculated"),
  ].join("");
  const maxViews = Math.max(...data.timeline.map((item) => item.views), 1);
  document.querySelector("#content-chart").innerHTML = data.timeline.length ? data.timeline.map((item) => `
    <div class="content-bar" title="${item.date} · ${item.views} visualizzazioni">
      <i style="height:${Math.max(item.views / maxViews * 100, 3)}%"></i>
      <span>${item.contents}</span><small>${item.date.slice(5)}</small>
    </div>`).join("") : empty("Nessun contenuto nel periodo selezionato.");
  const maxTopic = Math.max(...data.topics.map((topic) => topic.contents), 1);
  document.querySelector("#landscape-topics").innerHTML = data.topics.length ? data.topics.map((topic, index) => `
    <div class="ranked-row"><span>${String(index + 1).padStart(2, "0")} · ${escapeHtml(topic.name)}</span><i><b style="width:${topic.contents / maxTopic * 100}%"></b></i><strong>${topic.contents}</strong></div>`).join("") : empty("Nessun argomento disponibile.");
  document.querySelector("#top-content-list").innerHTML = data.top_contents.length ? data.top_contents.slice(0, 6).map((item) => `
    <article class="evidence-row content-row"><div><q>${escapeHtml(item.title)}</q><small>${escapeHtml(item.channel_title)} · ${item.engagement_rate}% interazioni/views</small></div><strong>${compact.format(item.views)}</strong></article>`).join("") : empty("Acquisisci un dataset per vedere i contenuti.");
  document.querySelector("#channel-list").innerHTML = data.channels.length ? data.channels.slice(0, 6).map((channel) => `
    <article class="evidence-row"><div><q>${escapeHtml(channel.name)}</q><small>${channel.contents} contenuti · media ${compact.format(channel.average_views)} views</small></div><strong>${compact.format(channel.views)}</strong></article>`).join("") : empty("Nessun canale disponibile.");
  const maxTerm = Math.max(...data.terms.map((term) => term.documents), 1);
  document.querySelector("#term-cloud").innerHTML = data.terms.length ? data.terms.slice(0, 12).map((term, index) => `
    <div class="ranked-row"><span>${String(index + 1).padStart(2, "0")} · ${escapeHtml(term.name)}</span><i><b style="width:${term.documents / maxTerm * 100}%"></b></i><strong>${term.documents}</strong></div>`).join("") : empty("Testo insufficiente per estrarre segnali.");
  const maxDuration = Math.max(...data.durations.map((item) => item.contents), 1);
  document.querySelector("#duration-list").innerHTML = data.durations.map((item) => `
    <div><span>${item.label}</span><i><b style="width:${item.contents / maxDuration * 100}%"></b></i><strong>${item.contents}</strong></div>`).join("");
  const maxQuery = Math.max(...data.queries.map((item) => item.contents), 1);
  document.querySelector("#query-list").innerHTML = data.queries.length ? data.queries.slice(0, 6).map((item) => `
    <div class="ranked-row"><span>${escapeHtml(item.query)}</span><i><b style="width:${item.contents / maxQuery * 100}%"></b></i><strong>${item.contents}</strong></div>`).join("") : empty("Nessuna query registrata.");
  const maxFormat = Math.max(...data.taxonomy.formats.map((item) => item.contents), 1);
  document.querySelector("#format-taxonomy").innerHTML = data.taxonomy.formats.map((item) => `
    <div class="ranked-row"><span>${escapeHtml(item.name)}</span><i><b style="width:${item.contents / maxFormat * 100}%"></b></i><strong>${item.contents}</strong></div>`).join("");
  const maxPurpose = Math.max(...data.taxonomy.purposes.map((item) => item.contents), 1);
  document.querySelector("#purpose-taxonomy").innerHTML = data.taxonomy.purposes.map((item) => `
    <div class="ranked-row"><span>${escapeHtml(item.name)}</span><i><b style="width:${item.contents / maxPurpose * 100}%"></b></i><strong>${item.contents}</strong></div>`).join("");
  document.querySelector("#tag-taxonomy").innerHTML = data.taxonomy.tags.length ? data.taxonomy.tags.map((item) => `
    <span>${escapeHtml(item.name)} <b>${item.documents}</b></span>`).join("") : empty("I record attuali non contengono tag. Una nuova acquisizione li importerà.");
  document.querySelector("#commercial-list").innerHTML = data.commercial_signals.items.length ? data.commercial_signals.items.map((item) => `
    <article><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.channel_title)}</small></div><span>${item.signals.map(escapeHtml).join(" · ")}</span></article>`).join("") : empty("Nessun indicatore commerciale testuale nel campione corrente.");
  renderRelationshipGraph(data.graph);
  renderPlatforms(data.platforms);
  const comparison = data.comparison;
  document.querySelector("#content-comparison").innerHTML = comparison ? `
    <div><p class="eyebrow">CONFRONTO DEI CONTENUTI</p><h3>${escapeHtml(comparison.left)} <i>×</i> ${escapeHtml(comparison.right)}</h3><small>Campione: ${comparison.sample_left} + ${comparison.sample_right} contenuti</small></div>
    <div><span>TERMINI CONDIVISI</span><p>${comparison.shared_terms.length ? comparison.shared_terms.map(escapeHtml).join(" · ") : "Nessuno nel campione"}</p></div>
    <div><span>DISTINTIVI · ${escapeHtml(comparison.left)}</span><p>${comparison.distinctive_left.map(escapeHtml).join(" · ") || "Nessuno"}</p></div>
    <div><span>DISTINTIVI · ${escapeHtml(comparison.right)}</span><p>${comparison.distinctive_right.map(escapeHtml).join(" · ") || "Nessuno"}</p></div>
    <strong>${comparison.channel_overlap}%<small>canali condivisi</small></strong>` : empty("Servono almeno due nicchie nel periodo per confrontare i contenuti.");
  const maxGrowth = Math.max(...data.trajectories.map((item) => Math.abs(item.growth_percent)), 1);
  document.querySelector("#trajectory-list").innerHTML = data.trajectories.length ? data.trajectories.map((item) => `
    <article class="trajectory-row">
      <div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.channel_title)} · ${item.observations} osservazioni${item.is_demo ? " · traiettoria demo simulata" : ""}</span><i class="trajectory-meter ${item.growth_percent < 0 ? "negative" : "positive"}"><b style="width:${Math.abs(item.growth_percent) / maxGrowth * 100}%"></b></i></div>
      <div><strong>${item.view_change > 0 ? "+" : ""}${compact.format(item.view_change)}</strong><span>variazione views</span></div>
      <div><strong>${item.growth_percent > 0 ? "+" : ""}${item.growth_percent}%</strong><span>nel periodo osservato</span></div>
      <div><strong>${compact.format(item.views_per_day)}/g</strong><span>velocità media</span></div>
    </article>`).join("") : empty("Servono almeno due snapshot dello stesso contenuto per calcolare una traiettoria.");
  document.querySelector("#last-updated").textContent = data.last_updated
    ? `Ultimo snapshot: ${new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(data.last_updated))}`
    : "Nessuno snapshot disponibile";
}

function renderAdvReport(data) {
  document.querySelector("#adv-metrics").innerHTML = [
    metric(data.metrics.contents_with_ads, "contenuti con segnali adv", "", "heuristic"),
    metric(data.metrics.sponsors_detected, "sponsor/aziende rilevati", "", "heuristic"),
    metric(data.metrics.channels_with_ads, "canali con adv", "", "heuristic"),
    metric(data.metrics.niches_with_ads, "nicchie con adv", "", "heuristic"),
  ].join("");

  const maxSponsorContents = Math.max(...data.top_sponsors.map((item) => item.contents), 1);
  document.querySelector("#adv-top-sponsors").innerHTML = data.top_sponsors.length ? data.top_sponsors.map((item, index) => `
    <article class="adv-sponsor-row ranked-sponsor">
      <span class="rank-index">${String(index + 1).padStart(2, "0")}</span>
      <div><strong>${escapeHtml(item.name)}</strong><small>${item.contents} contenuti · ${item.channels} canali · ${compact.format(item.total_views)} views</small><i><b style="width:${item.contents / maxSponsorContents * 100}%"></b></i></div>
      <span>${escapeHtml(item.niches.join(" · "))}</span>
    </article>`).join("") : empty("Nessuno sponsor rilevato nel periodo selezionato.");

  document.querySelector("#adv-sponsors-by-niche").innerHTML = data.sponsors_by_niche.length ? data.sponsors_by_niche.map((item) => `
    <article class="adv-niche-row">
      <strong>${escapeHtml(item.niche)}</strong>
      <small>${item.total_contents} contenuti adv</small>
      <div class="adv-tags">${item.sponsors.map((s) => `<span>${escapeHtml(s.name)} <b>${s.contents}</b></span>`).join("")}</div>
    </article>`).join("") : empty("Nessuna nicchia con segnali commerciali.");

  document.querySelector("#adv-channel-sponsors").innerHTML = data.channels_with_most_sponsors.length ? data.channels_with_most_sponsors.map((item) => `
    <article class="adv-channel-row">
      <strong>${escapeHtml(item.channel)}</strong>
      <small>${item.sponsors} sponsor · ${item.contents} contenuti</small>
      <div class="adv-tags">${item.sponsor_names.map((s) => `<span>${escapeHtml(s)}</span>`).join("")}</div>
    </article>`).join("") : empty("Nessun canale con sponsor multipli.");

  document.querySelector("#adv-cross-bridges").innerHTML = data.cross_niche_bridges.length ? data.cross_niche_bridges.map((item) => `
    <article class="adv-bridge-row">
      <strong>${escapeHtml(item.sponsor)}</strong>
      <small>${item.contents} contenuti · ${item.channels_total} canali</small>
      <div class="adv-tags">${item.niches.map((n) => `<span>${escapeHtml(n)}</span>`).join("")}</div>
    </article>`).join("") : empty("Nessuno sponsor attraversa più nicchie.");

  document.querySelector("#adv-indirect-niches").innerHTML = data.indirect_niches.length ? data.indirect_niches.map((item) => `
    <article class="adv-indirect-row">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <small>${item.contents} contenuti · ${item.channels_total} canali · ${compact.format(item.views)} views</small>
      </div>
      <div class="adv-indirect-detail">
        <span>CANALI</span><p>${escapeHtml(item.channels.join(" · "))}</p>
      </div>
      <div class="adv-indirect-detail">
        <span>NICCHIE</span><p>${escapeHtml(item.niches.join(" · "))}</p>
      </div>
      <div class="adv-indirect-detail">
        <span>SPONSOR CORRELATI</span><p>${item.related_sponsors.length ? item.related_sponsors.map((s) => `${escapeHtml(s.name)} (${s.shared_channels})`).join(" · ") : "Nessuno"}</p>
      </div>
    </article>`).join("") : empty("Nessuna nicchia indiretta ricostruibile.");

  const maxTrend = Math.max(...data.trends.map((item) => item.contents), 1);
  document.querySelector("#adv-trends").innerHTML = data.trends.length ? data.trends.map((item) => `
    <div class="adv-trend-bar" title="${item.month} · ${item.contents} contenuti · ${compact.format(item.views)} views">
      <span class="adv-trend-value">${item.contents}</span>
      <i style="height:${Math.max(item.contents / maxTrend * 100, 3)}%"></i>
      <small>${item.month.slice(5)}<b>${compact.format(item.views)}</b></small>
    </div>`).join("") : empty("Nessun andamento disponibile.");

  document.querySelector("#adv-content-list").innerHTML = data.ad_contents.length ? data.ad_contents.map((item) => `
    <article class="adv-content-row">
      <div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.channel)} · ${escapeHtml(item.niche)} · ${item.ad_type}</small></div>
      <div class="adv-content-meta">
        <span>${compact.format(item.views)} views</span>
        <span>${item.sponsors.map(escapeHtml).join(" · ")}</span>
        ${item.growth_percent !== null ? `<span class="${item.growth_percent >= 0 ? "positive" : "negative"}">${item.growth_percent > 0 ? "+" : ""}${item.growth_percent}%</span>` : ""}
      </div>
    </article>`).join("") : empty("Nessun contenuto con segnali commerciali.");
}

async function loadAdvReport() {
  const parameters = new URLSearchParams({ days: state.advDays, project_id: state.projectId });
  if (state.advNiche) parameters.set("niche", state.advNiche);
  const response = await fetch(`/api/adv/report?${parameters}`);
  if (!response.ok) throw new Error("Impossibile caricare il report adv");
  renderAdvReport(await response.json());
}

async function loadEntities() {
  const projectId = state.projectId;
  document.querySelector("#entity-list").innerHTML = empty("Caricamento entità...");
  let response = null;
  try {
    response = await fetch(`/api/entities?project_id=${projectId}&limit=200`);
  } catch (networkError) {
    if (projectId === state.projectId) document.querySelector("#entity-list").innerHTML = empty("Impossibile caricare le entità.");
    return;
  }
  if (projectId !== state.projectId) return;
  if (!response.ok) {
    document.querySelector("#entity-list").innerHTML = empty("Impossibile caricare le entità.");
    return;
  }
  const data = await response.json();
  state.sponsorEntities = data.items.filter((entity) => ["brand", "organization"].includes(entity.type));
  renderEntities(data.items);
  renderSponsorCompareOptions();
}

function renderEntities(entities) {
  const target = document.querySelector("#entity-list");
  target.innerHTML = entities.length ? entities.map((entity) => `
    <article class="entity-row" data-entity-id="${entity.id}">
      <div><strong>${escapeHtml(entity.name)}</strong><small>${entity.type}${entity.sector ? " · " + escapeHtml(entity.sector) : ""} · ${entity.mentions} menzioni</small></div>
      <div class="entity-actions">
        ${["brand", "organization"].includes(entity.type) ? `<button data-entity-basin="${entity.id}" type="button">Apri bacino</button>` : ""}
        <button data-entity-edit="${entity.id}" type="button">Modifica</button>
        <button data-entity-delete="${entity.id}" type="button">Elimina</button>
      </div>
    </article>`).join("") : empty("Nessuna entità estratta. Clicca \"Estrai entità dal corpus\" per iniziare.");
}

function renderSponsorCompareOptions() {
  const options = state.sponsorEntities.map((entity) => `<option value="${entity.id}">${escapeHtml(entity.name)}</option>`).join("");
  const left = document.querySelector("#sponsor-compare-left");
  const right = document.querySelector("#sponsor-compare-right");
  left.innerHTML = `<option value="">Seleziona un brand</option>${options}`;
  right.innerHTML = `<option value="">Seleziona un brand</option>${options}`;
  if (state.sponsorEntities.some((entity) => String(entity.id) === state.sponsorCompareLeft)) left.value = state.sponsorCompareLeft;
  if (state.sponsorEntities.some((entity) => String(entity.id) === state.sponsorCompareRight)) right.value = state.sponsorCompareRight;
}

function sponsorBars(items, valueKey, emptyMessage) {
  if (!items?.length) return empty(emptyMessage);
  const max = Math.max(...items.map((item) => Number(item[valueKey]) || 0), 1);
  return `<div class="sponsor-bars">${items.map((item) => {
    const value = Number(item[valueKey]) || 0;
    return `<div><span>${escapeHtml(item.name)}</span><i><b style="width:${value / max * 100}%"></b></i><strong>${compact.format(value)}</strong></div>`;
  }).join("")}</div>`;
}

function renderSponsorBasin(data) {
  const entity = data.entity;
  document.querySelector("#sponsor-basin-title").textContent = entity.name;
  document.querySelector("#sponsor-basin-subtitle").textContent = [entity.sector, `${data.metrics.channels} canali osservati`].filter(Boolean).join(" · ");
  document.querySelector("#sponsor-basin-content").innerHTML = `
    <div class="sponsor-basin-metrics">
      ${metric(data.metrics.channels, "canali nel bacino", "", "calculated")}
      ${metric(data.metrics.sponsored_contents, "contenuti sponsorizzati", "", "heuristic")}
      ${metric(compact.format(data.metrics.total_views), "views osservate")}
      ${metric(`${(Number(data.metrics.weighted_engagement_rate || 0) * 100).toFixed(2)}%`, "engagement pesato", "", "calculated")}
    </div>
    <div class="sponsor-profile-grid">
      <div><div class="subheading"><h4>Canali e piattaforme</h4><span>distribuzione</span></div>${sponsorBars(data.platforms, "channels", "Nessuna piattaforma disponibile.")}</div>
      <div><div class="subheading"><h4>Fasce creator</h4><span>iscritti dichiarati</span></div>${sponsorBars(data.subscriber_bands, "channels", "Fasce non disponibili.")}</div>
      <div><div class="subheading"><h4>Temi dominanti</h4><span>presenza nel bacino</span></div><div class="adv-tags sponsor-theme-list">${data.dominant_themes?.length ? data.dominant_themes.slice(0, 12).map((theme) => `<span>${escapeHtml(theme.term || theme.name || theme)}${theme.channels ? ` <b>${theme.channels}</b>` : ""}</span>`).join("") : "Nessun tema disponibile."}</div></div>
      <div><div class="subheading"><h4>Formati e scopi</h4><span>contenuti osservati</span></div>${sponsorBars([...(data.formats || []), ...(data.purposes || [])], "contents", "Formati non disponibili.")}</div>
    </div>
    <div class="sponsor-channel-section">
      <div class="subheading"><h4>Canali scelti dal brand</h4><span>ordinati per contenuti sponsorizzati</span></div>
      <div class="sponsor-channel-list">${data.channels?.length ? data.channels.map((channel) => `
        <article>
          <div><strong>${escapeHtml(channel.channel_title || channel.title || channel.channel_id)}</strong><small>${escapeHtml(channel.platform || "YouTube")} · ${compact.format(channel.subscribers || 0)} iscritti</small></div>
          <div class="adv-tags">${(channel.themes || []).slice(0, 4).map((theme) => `<span>${escapeHtml(theme.term || theme.name || theme)}</span>`).join("")}</div>
          <div><strong>${channel.sponsored_contents}</strong><small>contenuti · ${compact.format(channel.sponsored_views || 0)} views</small></div>
        </article>`).join("") : empty("Nessun canale associato a questo brand nel periodo.")}</div>
    </div>`;
  const form = document.querySelector("#sponsor-niche-form");
  form.hidden = !data.channels?.length;
  document.querySelector("#sponsor-niche-name").value = `Canali sponsorizzati da ${entity.name}`;
  document.querySelector("#sponsor-niche-status").textContent = "";
}

async function loadSponsorBasin(entityId, shouldScroll = true) {
  const projectId = state.projectId;
  state.sponsorEntityId = Number(entityId);
  const panel = document.querySelector("#sponsor-basin");
  panel.hidden = false;
  document.querySelector("#sponsor-basin-title").textContent = "Caricamento bacino...";
  document.querySelector("#sponsor-basin-subtitle").textContent = "Analisi dei canali sponsorizzati nel periodo selezionato";
  document.querySelector("#sponsor-basin-content").innerHTML = empty("Caricamento metriche, temi e canali...");
  document.querySelector("#sponsor-niche-form").hidden = true;
  if (shouldScroll) panel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await fetch(`/api/entities/${entityId}/sponsor-basin?days=${state.advDays}`);
    let data = null;
    try { data = await response.json(); } catch (parseError) { data = null; }
    if (projectId !== state.projectId || Number(entityId) !== state.sponsorEntityId) return;
    if (!response.ok || !data) throw new Error(data?.detail || "Impossibile caricare il bacino sponsor.");
    renderSponsorBasin(data);
  } catch (error) {
    if (projectId !== state.projectId || Number(entityId) !== state.sponsorEntityId) return;
    document.querySelector("#sponsor-basin-title").textContent = "Bacino non disponibile";
    document.querySelector("#sponsor-basin-content").innerHTML = empty(error.message);
  }
}

async function loadNicheBrands() {
  const target = document.querySelector("#niche-brand-list");
  const projectId = state.projectId;
  const niche = state.advNiche;
  if (!niche) {
    target.innerHTML = empty("Seleziona una nicchia nel filtro Adv per vedere i brand presenti.");
    return;
  }
  target.innerHTML = empty("Caricamento brand della nicchia...");
  const parameters = new URLSearchParams({ project_id: projectId, niche, days: state.advDays });
  try {
    const response = await fetch(`/api/adv/niches/brands?${parameters}`);
    let data = null;
    try { data = await response.json(); } catch (parseError) { data = null; }
    if (projectId !== state.projectId || niche !== state.advNiche) return;
    if (!response.ok || !data) throw new Error(data?.detail || "Impossibile caricare i brand della nicchia.");
    target.innerHTML = data.items.length ? data.items.map((item) => `
      <button class="niche-brand-row" data-entity-basin="${item.entity_id}" type="button">
        <span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.sector || "Brand")} · ${item.channels} canali</small><i><b style="width:${Math.min(Number(item.content_share) * 100, 100)}%"></b></i></span>
        <span class="brand-share"><strong>${(Number(item.content_share) * 100).toFixed(1)}%</strong><small>${item.sponsored_contents} contenuti</small></span>
      </button>`).join("") : empty("Nessun brand rilevato in questa nicchia nel periodo selezionato.");
  } catch (error) {
    if (projectId === state.projectId && niche === state.advNiche) target.innerHTML = empty(error.message);
  }
}

function comparisonBrandCard(side) {
  const themes = side.dominant_themes || [];
  return `<article class="sponsor-comparison-brand">
    <p class="eyebrow">BRAND</p><h4>${escapeHtml(side.entity.name)}</h4>
    <div><strong>${side.metrics.channels}</strong><span>canali</span><strong>${side.metrics.sponsored_contents}</strong><span>contenuti sponsorizzati</span><strong>${compact.format(side.metrics.total_views)}</strong><span>views</span></div>
    <div class="adv-tags">${themes.length ? themes.map((theme) => `<span>${escapeHtml(theme.term || theme.name || theme)}</span>`).join("") : "Nessun tema dominante"}</div>
  </article>`;
}

async function compareSponsorBasins(shouldScroll = true) {
  const target = document.querySelector("#sponsor-comparison");
  const left = document.querySelector("#sponsor-compare-left").value;
  const right = document.querySelector("#sponsor-compare-right").value;
  state.sponsorCompareLeft = left;
  state.sponsorCompareRight = right;
  if (!left || !right) {
    target.innerHTML = empty("Seleziona entrambi i brand per avviare il confronto.");
    return;
  }
  if (left === right) {
    target.innerHTML = empty("Seleziona due brand differenti.");
    return;
  }
  const projectId = state.projectId;
  target.innerHTML = empty("Confronto dei bacini in corso...");
  const parameters = new URLSearchParams({ project_id: projectId, left_entity_id: left, right_entity_id: right, days: state.advDays });
  try {
    const response = await fetch(`/api/adv/compare?${parameters}`);
    let data = null;
    try { data = await response.json(); } catch (parseError) { data = null; }
    if (projectId !== state.projectId || left !== state.sponsorCompareLeft || right !== state.sponsorCompareRight) return;
    if (!response.ok || !data) throw new Error(data?.detail || "Confronto non disponibile.");
    target.innerHTML = `${comparisonBrandCard(data.left)}
      <div class="sponsor-overlap">
        <span>OVERLAP CANALI</span><strong>${data.overlap.channels}</strong>
        <span>JACCARD</span><strong>${(Number(data.overlap.jaccard) * 100).toFixed(1)}%</strong>
        <small>${data.overlap.common.length ? data.overlap.common.map(escapeHtml).join(" · ") : "Nessun canale condiviso"}</small>
      </div>${comparisonBrandCard(data.right)}`;
    if (shouldScroll) target.scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (error) {
    if (projectId === state.projectId) target.innerHTML = empty(error.message);
  }
}

function resetSponsorWorkspace() {
  state.advNiche = "";
  state.sponsorEntityId = null;
  state.sponsorEntities = [];
  state.sponsorCompareLeft = "";
  state.sponsorCompareRight = "";
  document.querySelector("#sponsor-basin").hidden = true;
  document.querySelector("#sponsor-basin-content").innerHTML = "";
  document.querySelector("#create-sponsor-niche").disabled = false;
  document.querySelector("#sponsor-niche-status").textContent = "";
  document.querySelector("#sponsor-comparison").innerHTML = empty("Seleziona due brand per confrontare i rispettivi bacini.");
  document.querySelector("#niche-brand-list").innerHTML = empty("Seleziona una nicchia nel filtro Adv per vedere i brand presenti.");
  renderSponsorCompareOptions();
}

function openEntityDialog(entity = null) {
  const dialog = document.querySelector("#entity-dialog");
  const title = document.querySelector("#entity-dialog-title");
  document.querySelector("#entity-error").textContent = "";
  if (entity) {
    title.textContent = "Modifica entità";
    document.querySelector("#entity-id").value = entity.id;
    document.querySelector("#entity-name").value = entity.name;
    document.querySelector("#entity-type").value = entity.type;
    document.querySelector("#entity-sector").value = entity.sector || "";
    document.querySelector("#entity-aliases").value = (entity.aliases || []).join(", ");
  } else {
    title.textContent = "Crea entità";
    document.querySelector("#entity-form").reset();
    document.querySelector("#entity-id").value = "";
  }
  dialog.showModal();
}

async function saveEntity(event) {
  event.preventDefault();
  const error = document.querySelector("#entity-error");
  error.textContent = "";
  const id = document.querySelector("#entity-id").value;
  const payload = {
    project_id: state.projectId,
    name: document.querySelector("#entity-name").value,
    type: document.querySelector("#entity-type").value,
    sector: document.querySelector("#entity-sector").value,
    aliases: document.querySelector("#entity-aliases").value.split(",").map((s) => s.trim()).filter(Boolean),
  };
  const url = id ? `/api/entities/${id}` : "/api/entities";
  const method = id ? "PATCH" : "POST";
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    error.textContent = result.detail || "Salvataggio non riuscito.";
    return;
  }
  document.querySelector("#entity-dialog").close();
  await loadEntities();
  await loadAdvReport();
}

async function extractEntities() {
  const button = document.querySelector("#extract-entities");
  button.disabled = true;
  button.textContent = "Estrazione in coda...";
  const response = await fetch("/api/entities/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: state.projectId, full_refresh: true }),
  });
  if (response.ok) {
    await loadJobs();
  } else {
    button.textContent = "Errore";
  }
  setTimeout(() => { button.disabled = false; button.textContent = "Estrai entità dal corpus"; }, 2200);
}

async function runAdvSearch(query) {
  const target = document.querySelector("#adv-search-results");
  const summary = document.querySelector("#adv-search-summary");
  const matches = document.querySelector("#adv-search-matches");
  const channels = document.querySelector("#adv-search-channels");
  const niches = document.querySelector("#adv-search-niches");
  const trends = document.querySelector("#adv-search-trends");
  target.hidden = false;
  summary.textContent = "Ricerca in corso...";
  matches.innerHTML = empty("Caricamento...");
  channels.innerHTML = empty("Caricamento...");
  niches.innerHTML = empty("Caricamento...");
  trends.innerHTML = empty("Caricamento...");

  const response = await fetch("/api/adv/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: state.projectId, query }),
  });
  if (!response.ok) {
    summary.textContent = "Ricerca non riuscita";
    matches.innerHTML = empty("La ricerca non è disponibile.");
    return;
  }
  const data = await response.json();
  summary.textContent = `${data.metrics.matches} contenuti · ${data.metrics.channels} canali · ${data.metrics.niches} nicchie · ${compact.format(data.metrics.total_views)} views`;
  matches.innerHTML = data.matches.length ? data.matches.map((item) => `
    <article class="adv-content-row">
      <div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.channel)} · ${escapeHtml(item.niche)}</small></div>
      <div class="adv-content-meta">
        <span>${compact.format(item.views)} views</span>
        <span>${item.sponsors.map(escapeHtml).join(" · ") || "—"}</span>
        ${item.growth_percent !== null ? `<span class="${item.growth_percent >= 0 ? "positive" : "negative"}">${item.growth_percent > 0 ? "+" : ""}${item.growth_percent}%</span>` : ""}
      </div>
    </article>`).join("") : empty(`Nessun contenuto trovato per “${escapeHtml(query)}”.`);
  channels.innerHTML = data.channels.length ? data.channels.map((item) => `
    <article class="adv-channel-row">
      <strong>${escapeHtml(item.name)}</strong>
      <small>${item.contents} contenuti · media ${compact.format(item.avg_views)} views</small>
    </article>`).join("") : empty("Nessun canale trovato.");
  niches.innerHTML = data.niches.length ? data.niches.map((item) => `
    <article class="adv-niche-row">
      <strong>${escapeHtml(item.name)}</strong>
      <small>${item.contents} contenuti · ${item.channels} canali</small>
    </article>`).join("") : empty("Nessuna nicchia trovata.");
  const maxSearchTrend = Math.max(...data.trends.map((item) => item.contents), 1);
  trends.innerHTML = data.trends.length ? data.trends.map((item) => `
    <div class="adv-trend-bar" title="${item.month} · ${item.contents} contenuti">
      <span class="adv-trend-value">${item.contents}</span>
      <i style="height:${Math.max(item.contents / maxSearchTrend * 100, 3)}%"></i>
      <small>${item.month.slice(5)}</small>
    </div>`).join("") : empty("Nessun andamento per questa ricerca.");
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadChannelOverlap() {
  const parameters = new URLSearchParams({ project_id: state.projectId });
  if (state.niche) parameters.set("niche", state.niche);
  const response = await fetch(`/api/channels/overlap?${parameters}`);
  if (!response.ok) return;
  const data = await response.json();
  const maxOverlap = Math.max(...data.top_pairs.map((item) => Number(item.overlap)), 1);
  document.querySelector("#channel-overlap-list").innerHTML = data.top_pairs.length ? data.top_pairs.map((item) => `
    <article>
      <div><strong>${escapeHtml(item.left)}</strong><span>×</span><strong>${escapeHtml(item.right)}</strong></div>
      <i class="overlap-meter"><b style="width:${Number(item.overlap) / maxOverlap * 100}%"></b></i>
      <span>${(item.overlap * 100).toFixed(1)}%</span>
      <small>${item.shared_authors} autori</small>
    </article>`).join("") : empty("Servono almeno due canali con commentatori in comune per calcolare una sovrapposizione.");
}

function renderPlatforms(platforms) {
  document.querySelector("#platform-grid").innerHTML = platforms.items.length ? platforms.items.map((item) => `
    <article><span>${escapeHtml(item.name)}</span><strong>${item.contents}</strong><small>contenuti</small><p>${compact.format(item.views)} views · ${compact.format(item.interactions)} interazioni · ${item.channels} fonti</p></article>`).join("") : empty("Nessuna piattaforma nel corpus.");
  const comparison = platforms.comparison;
  document.querySelector("#platform-comparison").innerHTML = comparison ? `
    <div><span>CONFRONTO DEL LINGUAGGIO</span><strong>${escapeHtml(comparison.left)} × ${escapeHtml(comparison.right)}</strong></div>
    <div><span>CONDIVISI</span><p>${comparison.shared_terms.map(escapeHtml).join(" · ") || "Nessuno"}</p></div>
    <div><span>${escapeHtml(comparison.left)}</span><p>${comparison.distinctive_left.map(escapeHtml).join(" · ") || "Nessuno"}</p></div>
    <div><span>${escapeHtml(comparison.right)}</span><p>${comparison.distinctive_right.map(escapeHtml).join(" · ") || "Nessuno"}</p></div>` : empty("Importa contenuti da almeno due piattaforme per confrontarle.");
}

function renderRelationshipGraph(graph) {
  const svg = document.querySelector("#relationship-graph");
  if (!graph.nodes.length) {
    svg.innerHTML = '<rect class="graph-backdrop" x="16" y="50" width="868" height="340" rx="3"></rect><text x="450" y="220" text-anchor="middle" class="graph-empty">Nessuna relazione nel campione</text>';
    document.querySelector("#bridge-list").innerHTML = empty("Servono almeno due nicchie per individuare ponti.");
    return;
  }
  const columns = { niche: 105, channel: 450, topic: 795 };
  const labels = { niche: "NICCHIE", channel: "CANALI", topic: "ARGOMENTI" };
  const positions = new Map();
  ["niche", "channel", "topic"].forEach((type) => {
    const nodes = graph.nodes.filter((node) => node.type === type).sort((a, b) => b.size - a.size);
    nodes.forEach((node, index) => positions.set(node.id, {
      x: columns[type], y: 64 + (index + 1) * (310 / (nodes.length + 1)), node,
    }));
  });
  const edges = graph.edges.map((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return "";
    const bend = (target.x - source.x) * .48;
    return `<path class="graph-edge" data-source="${edge.source}" data-target="${edge.target}" d="M ${source.x} ${source.y} C ${source.x + bend} ${source.y}, ${target.x - bend} ${target.y}, ${target.x} ${target.y}" stroke-width="${Math.min(1 + Math.log2(edge.weight + 1), 5)}"><title>${edge.weight} contenuti collegati</title></path>`;
  }).join("");
  const nodes = [...positions.values()].map(({ x, y, node }) => {
    const anchor = node.type === "topic" ? "end" : "start";
    const textX = node.type === "topic" ? x - 14 : x + 14;
    const radius = Math.min(6 + Math.sqrt(node.size) * 3, 17);
    const description = `${node.label}, ${node.size} contenuti`;
    return `<g class="graph-node ${node.type}" data-node-id="${node.id}" tabindex="0" role="graphics-symbol" aria-label="${escapeHtml(description)}"><circle cx="${x}" cy="${y}" r="${radius}"><title>${escapeHtml(description)}</title></circle><text x="${textX}" y="${y - 1}" text-anchor="${anchor}">${escapeHtml(node.label)}</text><text class="graph-node-count" x="${textX}" y="${y + 10}" text-anchor="${anchor}">${node.size} contenuti</text></g>`;
  }).join("");
  const guides = Object.entries(columns).map(([type, x]) => `<line class="graph-guide" x1="${x}" y1="64" x2="${x}" y2="390"></line><text class="graph-column-label" x="${x}" y="35" text-anchor="middle">${labels[type]}</text>`).join("");
  svg.innerHTML = `<rect class="graph-backdrop" x="16" y="50" width="868" height="340" rx="3"></rect>${guides}${edges}${nodes}`;

  function highlightNode(nodeId) {
    const connected = new Set([nodeId]);
    svg.querySelectorAll(".graph-edge").forEach((edge) => {
      const active = edge.dataset.source === nodeId || edge.dataset.target === nodeId;
      edge.classList.toggle("is-active", active);
      edge.classList.toggle("is-muted", !active);
      if (active) connected.add(edge.dataset.source === nodeId ? edge.dataset.target : edge.dataset.source);
    });
    svg.querySelectorAll(".graph-node").forEach((node) => {
      node.classList.toggle("is-active", node.dataset.nodeId === nodeId);
      node.classList.toggle("is-muted", !connected.has(node.dataset.nodeId));
    });
  }

  function clearHighlight() {
    svg.querySelectorAll(".is-active, .is-muted").forEach((element) => element.classList.remove("is-active", "is-muted"));
  }

  svg.querySelectorAll(".graph-node").forEach((node) => {
    node.addEventListener("mouseenter", () => highlightNode(node.dataset.nodeId));
    node.addEventListener("focus", () => highlightNode(node.dataset.nodeId));
    node.addEventListener("blur", clearHighlight);
  });
  svg.onmouseleave = clearHighlight;
  document.querySelector("#bridge-list").innerHTML = graph.bridges.length ? graph.bridges.map((bridge) => `
    <article><span>${bridge.type === "channel" ? "CANALE" : "ARGOMENTO"}</span><strong>${escapeHtml(bridge.name)}</strong><small>${bridge.niches.map(escapeHtml).join(" ↔ ")}</small></article>`).join("") : empty("Nessun canale o argomento attraversa più nicchie nel campione.");
}

async function loadContentReport() {
  const parameters = new URLSearchParams({ days: state.days, project_id: state.projectId });
  if (state.niche) parameters.set("niche", state.niche);
  if (state.left && state.right) {
    parameters.set("left", state.left);
    parameters.set("right", state.right);
  }
  const response = await fetch(`/api/content/report?${parameters}`);
  if (!response.ok) throw new Error("Impossibile caricare il panorama dei contenuti");
  renderContentLandscape(await response.json());
  await loadChannelOverlap();
}

async function loadAllReports() {
  await Promise.allSettled([loadReport(), loadContentReport(), loadNlpSummary()]);
}

async function loadNlpSummary() {
  const response = await fetch(`/api/comments/analysis?project_id=${state.projectId}`);
  if (!response.ok) return;
  const data = await response.json();
  const sentiment = data.sentiment || {};
  const intent = data.intent || {};
  document.querySelector("#nlp-summary").innerHTML = `
    <div class="nlp-grid">
      <div><span>ANALIZZATI</span><strong>${data.analyzed}/${data.total_comments}</strong></div>
      <div><span>POSITIVI</span><strong>${sentiment.positive || 0}</strong></div>
      <div><span>NEGATIVI</span><strong>${sentiment.negative || 0}</strong></div>
      <div><span>FLAGGATI</span><strong class="${data.flagged ? 'warn' : ''}">${data.flagged}</strong></div>
    </div>
    <div class="intent-list">${Object.entries(intent).map(([key, value]) => `<span>${escapeHtml(key)} <b>${value}</b></span>`).join("") || empty("Nessun intento rilevato.")}</div>`;
}

async function loadReport() {
  const parameters = new URLSearchParams({ days: state.days, project_id: state.projectId });
  if (state.niche) parameters.set("niche", state.niche);
  if (state.left && state.right) {
    parameters.set("left", state.left);
    parameters.set("right", state.right);
  }
  const response = await fetch(`/api/report?${parameters}`);
  if (!response.ok) throw new Error("Impossibile caricare il report");
  const data = await response.json();
  document.querySelector("#metrics").innerHTML = [
    metric(compact.format(data.metrics.comments), "commenti osservati"),
    metric(compact.format(data.metrics.authors), "autori pseudonimi", "", "calculated"),
    metric(data.metrics.anomalies, "eventi anomali", data.metrics.anomalies ? "warn" : "", "heuristic"),
    metric(`${data.metrics.coordinated_share}%`, "in cluster ripetuti", "", "heuristic"),
  ].join("");
  renderActivity(data.activity);
  renderEvents(data.events);
  renderEvidence(data);
  renderNiches(data.niches);
  document.querySelector("#filter-status").textContent = state.niche
    ? `${state.days} giorni · ${state.niche}`
    : `${state.days} giorni · tutte le nicchie`;
}

async function loadNiches() {
  const response = await fetch(`/api/niches/summary?project_id=${state.projectId}`);
  if (!response.ok) throw new Error("Impossibile caricare le nicchie");
  const niches = await response.json();
  const options = niches.map((item) => `<option value="${escapeHtml(item.niche)}">${escapeHtml(item.niche)} · ${item.contents} video · ${item.comments} commenti</option>`).join("");
  document.querySelector("#niche-filter").innerHTML = `<option value="">Tutte le nicchie</option>${options}`;
  document.querySelector("#compare-left").innerHTML = options;
  document.querySelector("#compare-right").innerHTML = options;
  document.querySelector("#adv-niche").innerHTML = `<option value="">Tutte le nicchie</option>${options}`;
  if (niches.length > 1) {
    state.left = niches[0].niche;
    state.right = niches[1].niche;
    document.querySelector("#compare-right").selectedIndex = 1;
  } else {
    state.left = "";
    state.right = "";
  }
}

async function loadNicheEntities() {
  const response = await fetch(`/api/niches?project_id=${state.projectId}`);
  if (!response.ok) return;
  const niches = await response.json();
  state.nicheEntities = niches;
  document.querySelector("#niche-entities-list").innerHTML = niches.length ? niches.map((niche) => `
    <article class="source-row active">
      <div><strong>${escapeHtml(niche.name)}</strong><span>${escapeHtml(niche.status)} · ${niche.seed_channels.length} canali · ${niche.seed_videos.length} video · ${niche.include_keywords.length} keyword</span>${niche.description ? `<p>${escapeHtml(niche.description)}</p>` : ""}</div>
      <div class="source-actions">
        <button data-niche-edit="${niche.id}" type="button">Modifica</button>
        <button data-niche-discover="${niche.id}" type="button">Espandi bacino</button>
        <button data-niche-purge="${niche.id}" type="button">Elimina contenuti</button>
        <button data-niche-delete="${niche.id}" type="button">Elimina</button>
      </div>
    </article>`).join("") : empty("Nessuna nicchia definita. Crea la prima per iniziare a esplorare un bacino.");
}

function resetNicheForm() {
  const form = document.querySelector("#niche-form");
  form.reset();
  document.querySelector("#niche-edit-id").value = "";
  document.querySelector("#niche-dialog-eyebrow").textContent = "NUOVA NICCHIA";
  document.querySelector("#niche-dialog-title").textContent = "Definisci un bacino di ricerca";
  document.querySelector("#niche-submit").textContent = "Crea nicchia";
  document.querySelector("#niche-error").textContent = "";
}

function openNicheEdit(niche) {
  resetNicheForm();
  const filters = niche.filters || {};
  document.querySelector("#niche-edit-id").value = niche.id;
  document.querySelector("#niche-name").value = niche.name;
  document.querySelector("#niche-description").value = niche.description || "";
  document.querySelector("#niche-status").value = niche.status;
  document.querySelector("#niche-channels").value = (niche.seed_channels || []).map((channel) => channel.channel_id).join("\n");
  document.querySelector("#niche-videos").value = (niche.seed_videos || []).map((video) => video.video_id).join("\n");
  document.querySelector("#niche-include").value = (niche.include_keywords || []).join(", ");
  document.querySelector("#niche-exclude").value = (niche.exclude_keywords || []).join(", ");
  document.querySelector("#niche-region").value = filters.region_code || "";
  document.querySelector("#niche-language").value = filters.relevance_language || "";
  document.querySelector("#niche-min-subs").value = filters.min_subscribers || 0;
  document.querySelector("#niche-popular").value = filters.harvest_popular ? "true" : "false";
  document.querySelector("#niche-strict").value = filters.strict_geo ? "true" : "false";
  document.querySelector("#niche-auto-comments").value = filters.auto_fetch_comments === false ? "false" : "true";
  document.querySelector("#niche-max-comment-videos").value = String(filters.max_comment_videos || 5);
  document.querySelector("#niche-comments-per-video").value = String(filters.comments_per_video || 50);
  document.querySelector("#niche-include-replies").value = filters.include_replies ? "true" : "false";
  document.querySelector("#niche-dialog-eyebrow").textContent = "MODIFICA NICCHIA";
  document.querySelector("#niche-dialog-title").textContent = niche.name;
  document.querySelector("#niche-submit").textContent = "Salva modifiche";
}

function renderOnboarding() {
  const project = (state.projects || []).find((p) => p.id === state.projectId);
  const isEmpty = !project || (project.contents === 0 && project.comments === 0);
  const panel = document.querySelector("#onboarding-panel");
  const reportSections = [".metrics", "#landscape", "#adv", ".activity-section", "#integrity", "#niches", "#method"];
  panel.hidden = !isEmpty;
  reportSections.forEach((selector) => {
    const el = document.querySelector(selector);
    if (el) el.hidden = isEmpty;
  });
  const warning = document.querySelector("#onboarding-youtube-warning");
  if (warning) warning.hidden = state.youtubeConfigured;
}

async function loadProjects(selectId = state.projectId, autoOpen = true) {
  const response = await fetch("/api/projects");
  if (!response.ok) throw new Error("Impossibile caricare i progetti");
  const projects = await response.json();
  state.projects = projects;
  const select = document.querySelector("#project-filter");
  select.innerHTML = projects.map((project) => `<option value="${project.id}">${escapeHtml(project.name)} · ${project.contents} video · ${project.comments} commenti</option>`).join("");
  if (selectId && projects.find((p) => p.id === Number(selectId))) {
    state.projectId = Number(selectId);
  } else {
    const selected = projects[0];
    state.projectId = selected ? selected.id : null;
  }
  if (state.projectId) {
    select.value = String(state.projectId);
    document.querySelector("#delete-project").disabled = state.projectId === 1;
    document.querySelector("#header-project").textContent = state.projects.find((p) => p.id === state.projectId)?.name || "";
  }
  renderOnboarding();
  if (autoOpen && state.view !== "hub" && state.view !== "wizard") {
    await maybeOpenWizard();
  }
}

async function maybeOpenWizard() {
  if (!state.projectId) {
    startWizard(null, 1);
    return;
  }
  const project = state.projects.find((p) => p.id === state.projectId);
  if (!project || (project.contents === 0 && project.comments === 0)) {
    const nichesResponse = await fetch(`/api/niches?project_id=${state.projectId}`);
    const niches = nichesResponse.ok ? await nichesResponse.json() : [];
    if (!niches.length) {
      startWizard(state.projectId, project?.name ? 2 : 1);
    }
  }
}

async function loadSources() {
  const response = await fetch("/api/connectors/status");
  if (!response.ok) return;
  const data = await response.json();
  const source = data.youtube;
  state.youtubeConfigured = source.configured;
  const dot = document.querySelector("#youtube-dot");
  const status = document.querySelector("#youtube-status");
  const submit = document.querySelector("#youtube-submit");
  const discoverSubmit = document.querySelector("#discover-submit");
  const refreshSubmit = document.querySelector("#refresh-metrics");
  const bulkSubmit = document.querySelector("#bulk-comments-submit");
  dot.classList.toggle("ready", source.configured);
  status.textContent = source.configured
    ? "API configurata"
    : "API non configurata";
  submit.disabled = !source.configured;
  discoverSubmit.disabled = !source.configured;
  refreshSubmit.disabled = !source.configured;
  bulkSubmit.disabled = !source.configured;
  if (!source.configured) {
    document.querySelector("#source-message").innerHTML = "Per abilitare la fonte imposta <code>YOUTUBE_API_KEY</code> e riavvia il server. Il dataset demo e l'import CSV restano disponibili.";
  } else if (!source.pseudonym_salt_configured) {
    document.querySelector("#source-message").innerHTML = "Fonte pronta. Per ambienti non locali configura anche <code>PSEUDONYM_SALT</code> con un valore segreto stabile.";
  }
  renderOnboarding();
  await loadQuota();
}

async function loadQuota() {
  const element = document.querySelector("#quota-status");
  if (!element) return;
  const response = await fetch("/api/quota");
  if (!response.ok) return;
  const quota = await response.json();
  const percent = quota.daily_budget ? Math.round(quota.used_today / quota.daily_budget * 100) : 0;
  element.textContent = quota.daily_budget
    ? `Quota stimata oggi: ${compact.format(quota.used_today)} / ${compact.format(quota.daily_budget)} unità (${percent}%)`
    : "";
  element.classList.toggle("quota-warning", percent >= 80);
}

async function loadUser() {
  const response = await fetch("/api/auth/status");
  const data = await response.json();
  if (!data.authenticated) {
    window.location.href = "/login";
    return;
  }
  document.querySelector("#session-email").textContent = data.user.email;
}

async function loadMonitoring() {
  const response = await fetch(`/api/monitoring/runs?limit=5&project_id=${state.projectId}`);
  if (!response.ok) return;
  const data = await response.json();
  document.querySelector("#monitoring-status").textContent = data.active
    ? `Automatico ogni ${data.auto_refresh_hours} ore`
    : "Aggiornamento automatico disattivato";
  document.querySelector("#monitoring-runs").innerHTML = data.items.length ? data.items.map((run) => {
    const date = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(run.started_at));
    const label = run.trigger === "scheduled" ? "AUTO" : "MANUALE";
    return `<div class="monitoring-run ${run.status}"><span>${label}</span><strong>${date}</strong><small>${run.status === "completed" ? `${run.updated}/${run.requested} aggiornati` : escapeHtml(run.error || "in corso")}</small></div>`;
  }).join("") : empty("Nessun aggiornamento ancora registrato.");
}

async function loadJobs() {
  const response = await fetch(`/api/jobs?project_id=${state.projectId}&limit=8`);
  if (!response.ok) return;
  const data = await response.json();
  document.querySelector("#job-list").innerHTML = data.items.length ? data.items.map((job) => {
    const labels = {
      youtube_discovery: "Discovery YouTube",
      niche_discovery: "Espansione nicchia",
      youtube_bulk_comments: "Commenti dal corpus",
      comment_analysis: "Analisi commenti",
      entity_extraction: "Estrazione entità",
    };
    const running = ["queued", "running"].includes(job.status);
    return `<article class="job-row ${job.status}"><div><span>${escapeHtml(labels[job.job_type] || job.job_type)}</span><strong>${job.status}</strong></div><i><b style="width:${job.progress}%"></b></i><small>${job.progress}%</small>${running ? `<button data-cancel-job="${job.id}" type="button">Annulla</button>` : ""}${job.error ? `<p>${escapeHtml(job.error)}</p>` : ""}</article>`;
  }).join("") : empty("Nessun job per questo progetto.");
  let shouldReload = false;
  data.items.forEach((job) => {
    if (["completed", "failed", "cancelled"].includes(job.status) && !handledJobs.has(job.id)) {
      handledJobs.add(job.id);
      shouldReload = shouldReload || job.status === "completed";
    }
  });
  if (shouldReload) {
    await loadProjects(state.projectId);
    await loadNiches();
    await loadSourcesList();
    await loadAllReports();
    await loadEntities();
    await loadAdvReport();
  }
}

async function loadSourcesList() {
  const response = await fetch(`/api/sources?project_id=${state.projectId}`);
  if (!response.ok) return;
  const data = await response.json();
  const formatDate = (value) => value
    ? new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value))
    : "--";
  document.querySelector("#sources-list").innerHTML = data.items.length ? data.items.map((source) => {
    const active = source.status === "active";
    return `<article class="source-row ${active ? "active" : "paused"}">
      <div><strong>${escapeHtml(source.name)}</strong><span>${escapeHtml(source.source_type)} · ogni ${source.refresh_hours}h</span>${source.last_error ? `<p class="source-error">${escapeHtml(source.last_error)}</p>` : ""}</div>
      <div class="source-runs"><span>ultima</span><strong>${formatDate(source.last_run_at)}</strong><span>prossima</span><strong>${formatDate(source.next_run_at)}</strong></div>
      <div class="source-actions">
        <button data-source-run="${source.id}" type="button">Rilancia</button>
        <button data-source-edit="${source.id}" data-name="${escapeHtml(source.name)}" data-refresh="${source.refresh_hours}" type="button">Modifica</button>
        <button data-source-toggle="${source.id}" data-status="${active ? "paused" : "active"}" type="button">${active ? "Pausa" : "Riprendi"}</button>
        <button data-source-delete="${source.id}" type="button">Elimina</button>
      </div>
    </article>`;
  }).join("") : empty("Nessuna fonte monitorata. La prima discovery crea automaticamente una fonte.");
}

async function runSearch(query) {
  const parameters = new URLSearchParams({ q: query, project_id: state.projectId });
  if (state.niche) parameters.set("niche", state.niche);
  const target = document.querySelector("#search-results");
  target.innerHTML = '<p class="empty">Ricerca in corso...</p>';
  const response = await fetch(`/api/comments/search?${parameters}`);
  if (!response.ok) {
    target.innerHTML = empty("La ricerca non è disponibile.");
    return;
  }
  const data = await response.json();
  target.innerHTML = data.items.length ? `
    <div class="search-summary">${data.count} risultati per “${escapeHtml(data.query)}”</div>
    ${data.items.map((item) => {
      const date = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(item.published_at));
      return `<article class="search-result"><p>${escapeHtml(item.text)}</p><span>${escapeHtml(item.author_hash)} · ${escapeHtml(item.niche)} · ${date}</span><small>${escapeHtml(item.content_title || item.content_id)}</small></article>`;
    }).join("")}` : empty(`Nessun commento contiene “${escapeHtml(data.query)}”.`);
}

document.querySelector("#today").textContent = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short" }).format(new Date()).toUpperCase();
document.querySelector("#logout-button").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
});
document.querySelector("#account-button").addEventListener("click", async () => {
  document.querySelector("#password-error").textContent = "";
  document.querySelector("#password-ok").textContent = "";
  document.querySelector("#password-form").reset();
  await loadSessions();
  document.querySelector("#account-dialog").showModal();
});
document.querySelector("#cancel-account").addEventListener("click", () => document.querySelector("#account-dialog").close());

async function loadSessions() {
  const response = await fetch("/api/auth/sessions");
  if (!response.ok) return;
  const data = await response.json();
  const formatDate = (value) => new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  document.querySelector("#sessions-list").innerHTML = data.items.length ? data.items.map((session) => `
    <article class="source-row active">
      <div><strong>${session.current ? "Questo dispositivo" : `Sessione ${escapeHtml(session.id)}`}</strong><span>creata ${formatDate(session.created_at)} · scade ${formatDate(session.expires_at)}</span></div>
    </article>`).join("") : empty("Nessuna sessione attiva.");
}

document.querySelector("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#password-error");
  const ok = document.querySelector("#password-ok");
  error.textContent = "";
  ok.textContent = "";
  const response = await fetch("/api/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: document.querySelector("#password-current").value,
      new_password: document.querySelector("#password-new").value,
    }),
  });
  const result = await response.json();
  if (!response.ok) {
    error.textContent = result.detail || "Cambio password non riuscito.";
    return;
  }
  ok.textContent = "Password aggiornata. Le altre sessioni sono state disconnesse.";
  document.querySelector("#password-form").reset();
  await loadSessions();
});
document.querySelector("#revoke-sessions").addEventListener("click", async () => {
  const response = await fetch("/api/auth/sessions/revoke-others", { method: "POST" });
  if (response.ok) await loadSessions();
});
document.querySelector("#project-filter").addEventListener("change", async (event) => {
  state.projectId = Number(event.target.value);
  state.niche = "";
  resetSponsorWorkspace();
  document.querySelector("#delete-project").disabled = state.projectId === 1;
  await loadNiches();
  await loadAllReports();
  await loadJobs();
  await loadSourcesList();
  await Promise.allSettled([loadEntities(), loadAdvReport(), loadNicheBrands()]);
});
document.querySelector("#manage-niches").addEventListener("click", async () => {
  resetNicheForm();
  await loadNicheEntities();
  document.querySelector("#niches-dialog").showModal();
});
document.querySelector("#cancel-niche").addEventListener("click", () => document.querySelector("#niches-dialog").close());
function geoFilters(prefix) {
  const region = document.querySelector(`#${prefix}-region`).value.trim().toUpperCase();
  const language = document.querySelector(`#${prefix}-language`).value.trim().toLowerCase();
  const minSubs = Number(document.querySelector(`#${prefix}-min-subs`).value) || 0;
  const maxSubsElement = document.querySelector(`#${prefix}-max-subs`);
  const maxSubs = Number(maxSubsElement?.value) || 0;
  const popular = document.querySelector(`#${prefix}-popular`).value === "true";
  const strict = document.querySelector(`#${prefix}-strict`).value === "true";
  const filters = {};
  if (region) {
    filters.region_code = region;
    filters.channel_country = region;
  }
  if (language) {
    filters.relevance_language = language;
    filters.channel_language = language;
  }
  if (minSubs) filters.min_subscribers = minSubs;
  if (maxSubs) filters.max_subscribers = maxSubs;
  if (popular) filters.harvest_popular = true;
  if (strict) filters.strict_geo = true;
  return filters;
}

document.querySelector("#niche-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#niche-error");
  error.textContent = "";
  const seedChannels = document.querySelector("#niche-channels").value.split("\n").map((s) => s.trim()).filter(Boolean).map((value) => ({ channel_id: value, channel_title: value }));
  const seedVideos = document.querySelector("#niche-videos").value.split("\n").map((s) => s.trim()).filter(Boolean).map((value) => ({ video_id: value, title: value }));
  const includeKeywords = document.querySelector("#niche-include").value.split(",").map((s) => s.trim()).filter(Boolean);
  const excludeKeywords = document.querySelector("#niche-exclude").value.split(",").map((s) => s.trim()).filter(Boolean);
  const editId = document.querySelector("#niche-edit-id").value;
  const existing = editId
    ? (state.nicheEntities || []).find((item) => item.id === Number(editId))
    : null;
  const payload = {
    name: document.querySelector("#niche-name").value,
    description: document.querySelector("#niche-description").value,
    status: document.querySelector("#niche-status").value,
    seed_channels: seedChannels,
    seed_videos: seedVideos,
    include_keywords: includeKeywords,
    exclude_keywords: excludeKeywords,
    definition: { ...(existing?.definition || {}) },
    filters: {
      ...(existing?.filters || {}),
      region_code: "",
      channel_country: "",
      relevance_language: "",
      channel_language: "",
      min_subscribers: 0,
      harvest_popular: false,
      strict_geo: false,
      auto_fetch_comments: document.querySelector("#niche-auto-comments").value === "true",
      max_comment_videos: Number(document.querySelector("#niche-max-comment-videos").value),
      comments_per_video: Number(document.querySelector("#niche-comments-per-video").value),
      include_replies: document.querySelector("#niche-include-replies").value === "true",
      ...geoFilters("niche"),
    },
  };
  const response = editId
    ? await fetch(`/api/niches/${editId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    : await fetch("/api/niches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: state.projectId, ...payload }),
      });
  const result = await response.json();
  if (!response.ok) {
    error.textContent = result.detail || (editId ? "Salvataggio non riuscito." : "Creazione non riuscita.");
    return;
  }
  resetNicheForm();
  await loadNicheEntities();
  await loadNiches();
});
document.querySelector("#niche-entities-list").addEventListener("click", async (event) => {
  const discover = event.target.closest("[data-niche-discover]");
  const remove = event.target.closest("[data-niche-delete]");
  const edit = event.target.closest("[data-niche-edit]");
  const purge = event.target.closest("[data-niche-purge]");
  if (edit) {
    const niche = (state.nicheEntities || []).find((item) => item.id === Number(edit.dataset.nicheEdit));
    if (niche) openNicheEdit(niche);
    return;
  }
  if (purge) {
    const niche = (state.nicheEntities || []).find((item) => item.id === Number(purge.dataset.nichePurge));
    if (!niche) return;
    if (!window.confirm(`Eliminare i contenuti del progetto collegati alla nicchia "${niche.name}"? La definizione della nicchia resta.`)) return;
    const response = await fetch(`/api/projects/${state.projectId}/contents?niche=${encodeURIComponent(niche.name)}`, { method: "DELETE" });
    const result = await response.json();
    const message = document.querySelector("#source-message");
    message.textContent = response.ok
      ? `Scollegati ${result.detached} contenuti dalla nicchia "${niche.name}" (${result.orphans_removed} eliminati definitivamente).`
      : result.detail || "Eliminazione contenuti non riuscita.";
    if (response.ok) {
      await loadProjects(state.projectId);
      await loadNiches();
      await loadAllReports();
    }
    return;
  }
  if (discover) {
    const message = document.querySelector("#source-message");
    message.textContent = "Espansione del bacino inserita in coda. Consuma quota API YouTube.";
    const response = await fetch(`/api/niches/${discover.dataset.nicheDiscover}/discover`, { method: "POST" });
    const result = await response.json();
    if (response.ok) {
      message.textContent = `Espansione nicchia "${escapeHtml(result.niche)}" in coda come job #${result.job.id}.`;
      document.querySelector("#niches-dialog").close();
      await loadJobs();
      await loadQuota();
    } else {
      message.textContent = result.detail || "Espansione non riuscita.";
    }
    return;
  }
  if (remove && window.confirm("Eliminare questa nicchia? I contenuti associati non verranno cancellati.")) {
    const response = await fetch(`/api/niches/${remove.dataset.nicheDelete}`, { method: "DELETE" });
    if (response.ok) await loadNicheEntities();
  }
});
document.querySelector("#delete-project").addEventListener("click", async () => {
  if (state.projectId === 1 || !window.confirm("Eliminare questo progetto e le relative associazioni?")) return;
  const response = await fetch(`/api/projects/${state.projectId}`, { method: "DELETE" });
  if (!response.ok) return;
  state.projectId = 1;
  state.niche = "";
  resetSponsorWorkspace();
  await loadProjects(1);
  await loadNiches();
  await loadAllReports();
  await Promise.allSettled([loadEntities(), loadAdvReport(), loadNicheBrands()]);
});
document.querySelector("#period-filter").addEventListener("change", async (event) => {
  state.days = Number(event.target.value);
  await loadAllReports();
});
document.querySelector("#niche-filter").addEventListener("change", async (event) => {
  state.niche = event.target.value;
  await loadAllReports();
});
document.querySelector("#reset-filters").addEventListener("click", async () => {
  state.days = 14;
  state.niche = "";
  document.querySelector("#period-filter").value = "14";
  document.querySelector("#niche-filter").value = "";
  await loadAllReports();
});
document.querySelector("#compare-button").addEventListener("click", async () => {
  state.left = document.querySelector("#compare-left").value;
  state.right = document.querySelector("#compare-right").value;
  if (state.left === state.right) {
    document.querySelector("#comparison").innerHTML = empty("Seleziona due nicchie differenti.");
    return;
  }
  state.niche = "";
  document.querySelector("#niche-filter").value = "";
  await loadAllReports();
  document.querySelector("#comparison").scrollIntoView({ behavior: "smooth", block: "center" });
});
document.querySelector("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await runSearch(document.querySelector("#search-input").value.trim());
});
document.querySelector("#analyze-comments").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Analisi in coda...";
  const response = await fetch("/api/comments/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: state.projectId, limit: 500 }),
  });
  const result = await response.json();
  if (response.ok) {
    await loadJobs();
  } else {
    button.textContent = result.detail || "Errore";
  }
  setTimeout(() => { button.disabled = false; button.textContent = "Avvia analisi commenti"; }, 2200);
});
document.querySelector("#youtube-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#youtube-submit");
  const message = document.querySelector("#source-message");
  button.disabled = true;
  button.textContent = "Acquisizione...";
  message.textContent = "Interrogazione dell'API ufficiale YouTube in corso.";
  const response = await fetch("/api/sources/youtube/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video: document.querySelector("#youtube-video").value,
      niche: document.querySelector("#youtube-niche").value,
      topic: document.querySelector("#youtube-topic").value,
      max_comments: Number(document.querySelector("#youtube-limit").value),
      project_id: state.projectId,
    }),
  });
  const result = await response.json();
  if (response.ok) {
    message.textContent = `${result.video.title}: ${result.imported} nuovi commenti su ${result.received} ricevuti.`;
    await loadNiches();
    await loadAllReports();
    await loadQuota();
  } else {
    message.textContent = result.detail || "Acquisizione non riuscita.";
  }
  button.disabled = false;
  button.textContent = "Importa commenti →";
});
document.querySelector("#youtube-discover-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#discover-submit");
  const message = document.querySelector("#source-message");
  button.disabled = true;
  button.textContent = "Acquisizione...";
  message.textContent = "Ricerca e acquisizione delle metriche pubbliche in corso. Questa operazione consuma quota API.";
  const response = await fetch("/api/sources/youtube/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: document.querySelector("#discover-query").value,
      niche: document.querySelector("#discover-niche").value,
      topic: document.querySelector("#discover-topic").value,
      days: Number(document.querySelector("#discover-days").value),
      max_results: Number(document.querySelector("#discover-limit").value),
      project_id: state.projectId,
    }),
  });
  const result = await response.json();
  if (response.ok) {
    message.textContent = `Discovery inserita in coda come job #${result.job.id}.`;
    await loadJobs();
    await loadQuota();
  } else {
    message.textContent = result.detail || "Acquisizione non riuscita.";
  }
  button.disabled = false;
  button.textContent = "Cerca e acquisisci →";
});
document.querySelector("#bulk-comments-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#bulk-comments-submit");
  const message = document.querySelector("#source-message");
  button.disabled = true;
  button.textContent = "Acquisizione...";
  const response = await fetch("/api/sources/youtube/comments/bulk", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: state.projectId,
      niche: state.niche || null,
      video_limit: Number(document.querySelector("#bulk-video-limit").value),
      comments_per_video: Number(document.querySelector("#bulk-comment-limit").value),
    }),
  });
  const result = await response.json();
  if (response.ok) {
    message.textContent = `Acquisizione commenti inserita in coda come job #${result.job.id}.`;
    await loadJobs();
    await loadQuota();
  } else {
    message.textContent = result.detail || "Acquisizione non riuscita.";
  }
  button.disabled = false;
  button.textContent = "Acquisisci dal corpus →";
});
document.querySelector("#refresh-metrics").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Aggiornamento...";
  const response = await fetch("/api/sources/youtube/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ niche: state.niche || null, limit: 200, project_id: state.projectId }),
  });
  const result = await response.json();
  if (response.ok) {
    button.textContent = result.updated ? `${result.updated} aggiornati` : "Nessun video reale";
    await loadContentReport();
    await loadMonitoring();
    await loadQuota();
  } else {
    button.textContent = result.detail || "Aggiornamento fallito";
  }
  setTimeout(() => { button.textContent = original; button.disabled = false; }, 2200);
});
document.querySelector("#job-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-cancel-job]");
  if (!button) return;
  await fetch(`/api/jobs/${button.dataset.cancelJob}`, { method: "DELETE" });
  await loadJobs();
});
document.querySelector("#sources-list").addEventListener("click", async (event) => {
  const run = event.target.closest("[data-source-run]");
  const toggle = event.target.closest("[data-source-toggle]");
  const remove = event.target.closest("[data-source-delete]");
  const edit = event.target.closest("[data-source-edit]");
  if (run) {
    await fetch(`/api/sources/${run.dataset.sourceRun}/run`, { method: "POST" });
    await Promise.all([loadSourcesList(), loadJobs()]);
    return;
  }
  if (edit) {
    const name = window.prompt("Nome della fonte:", edit.dataset.name);
    if (name === null) return;
    const refresh = window.prompt("Frequenza di aggiornamento (ore, 1-720):", edit.dataset.refresh);
    if (refresh === null) return;
    const payload = {};
    if (name.trim()) payload.name = name.trim();
    const hours = Number(refresh);
    if (Number.isInteger(hours) && hours >= 1 && hours <= 720) payload.refresh_hours = hours;
    const response = await fetch(`/api/sources/${edit.dataset.sourceEdit}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      await loadSourcesList();
    } else {
      const result = await response.json();
      window.alert(result.detail || "Modifica non riuscita.");
    }
    return;
  }
  if (toggle) {
    await fetch(`/api/sources/${toggle.dataset.sourceToggle}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: toggle.dataset.status }),
    });
    await loadSourcesList();
    return;
  }
  if (remove && window.confirm("Eliminare questa fonte? I dati già acquisiti restano nel progetto.")) {
    await fetch(`/api/sources/${remove.dataset.sourceDelete}`, { method: "DELETE" });
    await loadSourcesList();
  }
});
document.querySelector("#csv-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const status = document.querySelector("#import-status");
  status.textContent = "Importazione in corso...";
  const response = await fetch("/api/import", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ csv_text: await file.text(), project_id: state.projectId }),
  });
  const result = await response.json();
  status.textContent = response.ok ? `${result.imported} nuovi commenti importati` : result.detail;
  if (response.ok) await loadAllReports();
});
document.querySelector("#content-csv-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const status = document.querySelector("#import-status");
  status.textContent = "Importazione contenuti in corso...";
  const response = await fetch("/api/import/contents", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ csv_text: await file.text(), project_id: state.projectId }),
  });
  const result = await response.json();
  status.textContent = response.ok ? `${result.imported} contenuti collegati al progetto` : result.detail;
  if (response.ok) {
    await loadProjects(state.projectId);
    await loadNiches();
    await loadContentReport();
  }
});
function exportUrl(path) {
  const parameters = new URLSearchParams({ project_id: state.projectId });
  if (state.niche) parameters.set("niche", state.niche);
  return `${path}?${parameters}`;
}
document.querySelector("#export-contents").addEventListener("click", () => { window.location.href = exportUrl("/api/export/contents.csv"); });
document.querySelector("#export-comments").addEventListener("click", () => { window.location.href = exportUrl("/api/export/comments.csv"); });
document.querySelector("#print-report").addEventListener("click", () => window.print());

document.querySelector("#expand-adv").addEventListener("click", async () => {
  document.querySelector("#adv").scrollIntoView({ behavior: "smooth", block: "start" });
  await Promise.all([loadAdvReport(), loadEntities()]);
});

document.querySelector("#new-entity").addEventListener("click", () => openEntityDialog());
document.querySelector("#cancel-entity").addEventListener("click", () => document.querySelector("#entity-dialog").close());
document.querySelector("#entity-form").addEventListener("submit", saveEntity);
document.querySelector("#extract-entities").addEventListener("click", extractEntities);
document.querySelector("#entity-list").addEventListener("click", async (event) => {
  const basin = event.target.closest("[data-entity-basin]");
  const edit = event.target.closest("[data-entity-edit]");
  const remove = event.target.closest("[data-entity-delete]");
  if (basin) {
    await loadSponsorBasin(Number(basin.dataset.entityBasin));
    return;
  }
  if (edit) {
    const response = await fetch(`/api/entities/${edit.dataset.entityEdit}`);
    if (response.ok) openEntityDialog(await response.json());
    return;
  }
  if (remove && window.confirm("Eliminare questa entità? Le menzioni associate verranno rimosse.")) {
    const response = await fetch(`/api/entities/${remove.dataset.entityDelete}`, { method: "DELETE" });
    if (response.ok) {
      await loadEntities();
      await loadAdvReport();
    }
  }
});

document.querySelector("#adv-period").addEventListener("change", async (event) => {
  state.advDays = Number(event.target.value);
  await Promise.allSettled([
    loadAdvReport(),
    loadNicheBrands(),
    state.sponsorEntityId ? loadSponsorBasin(state.sponsorEntityId, false) : Promise.resolve(),
    state.sponsorCompareLeft && state.sponsorCompareRight ? compareSponsorBasins(false) : Promise.resolve(),
  ]);
});

document.querySelector("#adv-niche").addEventListener("change", async (event) => {
  state.advNiche = event.target.value;
  await Promise.allSettled([loadAdvReport(), loadNicheBrands()]);
});

document.querySelector("#adv-refresh").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Aggiornamento...";
  try {
    await Promise.allSettled([
      loadAdvReport(),
      loadNicheBrands(),
      state.sponsorEntityId ? loadSponsorBasin(state.sponsorEntityId, false) : Promise.resolve(),
    ]);
  } finally {
    button.disabled = false;
    button.textContent = "Aggiorna report";
  }
});

document.querySelector("#adv-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await runAdvSearch(document.querySelector("#adv-search-input").value.trim());
});

document.querySelector("#close-sponsor-basin").addEventListener("click", () => {
  state.sponsorEntityId = null;
  document.querySelector("#sponsor-basin").hidden = true;
});
document.querySelector("#niche-brand-list").addEventListener("click", async (event) => {
  const brand = event.target.closest("[data-entity-basin]");
  if (brand) await loadSponsorBasin(Number(brand.dataset.entityBasin));
});
document.querySelector("#sponsor-compare-button").addEventListener("click", compareSponsorBasins);
document.querySelector("#sponsor-niche-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.sponsorEntityId) return;
  const button = document.querySelector("#create-sponsor-niche");
  const status = document.querySelector("#sponsor-niche-status");
  const projectId = state.projectId;
  button.disabled = true;
  status.className = "";
  status.textContent = "Creazione della nicchia in corso...";
  let result = null;
  let response = null;
  try {
    response = await fetch("/api/niches/from-sponsor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        entity_id: state.sponsorEntityId,
        name: document.querySelector("#sponsor-niche-name").value.trim(),
        days: state.advDays,
        platform: null,
      }),
    });
    try { result = await response.json(); } catch (parseError) { result = null; }
  } catch (networkError) {
    result = null;
  }
  if (projectId !== state.projectId) return;
  button.disabled = false;
  if (!response?.ok || !result) {
    status.className = "error";
    status.textContent = result?.detail || "Creazione della nicchia non riuscita.";
    return;
  }
  status.className = "success";
  status.textContent = `Nicchia creata con ${result.channels} canali e ${result.contents} contenuti.`;
  await loadNiches();
});

function showView(view) {
  state.view = view;
  document.querySelectorAll(".app-view").forEach((el) => el.hidden = true);
  document.querySelector("#project-hub").hidden = view !== "hub";
  document.querySelector("#onboarding-wizard").hidden = view !== "wizard";
  document.querySelector("#overview").hidden = view !== "dashboard";
  const activeNav = document.querySelector("nav a.active");
  if (activeNav) activeNav.classList.remove("active");
  if (view === "dashboard") {
    const overviewLink = document.querySelector("nav a[href='#overview']");
    if (overviewLink) overviewLink.classList.add("active");
  }
}

async function openProjectHub() {
  await loadProjects(null, false);
  showView("hub");
  renderProjectHub();
}

function renderProjectHub() {
  const empty = document.querySelector("#hub-empty");
  const withProjects = document.querySelector("#hub-with-projects");
  const grid = document.querySelector("#project-hub-grid");
  if (!state.projects.length) {
    empty.hidden = false;
    withProjects.hidden = true;
    return;
  }
  empty.hidden = true;
  withProjects.hidden = false;
  grid.innerHTML = state.projects.map((project) => `
    <article class="project-card ${project.id === state.projectId ? "active" : ""}" data-project-id="${project.id}">
      <h3>${escapeHtml(project.name)}</h3>
      <p>${escapeHtml(project.description || "Nessuna descrizione")}</p>
      <div class="project-stats">
        <span><strong>${project.contents}</strong> contenuti</span>
        <span><strong>${project.comments}</strong> commenti</span>
      </div>
      <div class="project-actions">
        <button data-open-project="${project.id}" type="button">Apri</button>
        ${project.id !== 1 ? `<button data-delete-project="${project.id}" type="button">Elimina</button>` : ""}
      </div>
    </article>`).join("");
}

async function openProject(projectId) {
  state.projectId = projectId;
  state.niche = "";
  resetSponsorWorkspace();
  showView("dashboard");
  await loadProjects(projectId, false);
  await Promise.allSettled([loadNiches(), loadSources(), loadMonitoring(), loadJobs(), loadSourcesList(), loadAllReports(), loadAdvReport(), loadEntities(), loadNicheBrands()]);
}

async function deleteProjectFromHub(projectId) {
  if (!window.confirm("Eliminare questo progetto e le relative associazioni?")) return;
  const response = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
  if (!response.ok) return;
  await loadProjects(null, false);
  renderProjectHub();
}

function wizardCollectionFilters() {
  const filters = {
    date_window_days: Number(document.querySelector("#wizard-niche-days").value) || 90,
    max_results: Number(document.querySelector("#wizard-niche-max-results").value) || 200,
    min_views: Number(document.querySelector("#wizard-niche-min-views").value) || 0,
    ...geoFilters("wizard-niche"),
  };
  if (state.wizardMode === "channels") {
    filters.include_top_channels = document.querySelector("#wizard-niche-top-channels").value === "true";
    filters.evidence_depth = document.querySelector("#wizard-evidence-depth").value;
    filters.second_wave_top_k = Number(document.querySelector("#wizard-second-wave").value) || 0;
    filters.cross_theme_ranking = document.querySelector("#wizard-cross-theme").checked;
    ["theme", "geo", "size", "popularity", "engagement", "velocity"].forEach((name) => {
      filters[`w_${name}`] = Math.max(0, Number(document.querySelector(`#wizard-weight-${name}`).value) || 0);
    });
  }
  return filters;
}

function wizardClientFilters() {
  const list = (selector) => document.querySelector(selector).value.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean);
  return {
    min_subscribers: Number(document.querySelector("#preview-min-subs").value) || 0,
    max_subscribers: Number(document.querySelector("#preview-max-subs").value) || 0,
    min_views: Number(document.querySelector("#preview-channel-min-views").value) || 0,
    max_views: Number(document.querySelector("#preview-channel-max-views").value) || 0,
    min_score: Number(document.querySelector("#preview-min-score").value) || 0,
    themes_include: list("#preview-themes-include"),
    themes_exclude: list("#preview-themes-exclude"),
    promoted_only: document.querySelector("#preview-promoted-only").checked,
  };
}

function updateWizardQuotaEstimate() {
  const channels = document.querySelector("#wizard-niche-channels").value.split("\n").filter((value) => value.trim()).length;
  const keywords = document.querySelector("#wizard-niche-include").value.split(",").filter((value) => value.trim()).length;
  const searches = Math.min(channels + keywords, 10);
  const popular = document.querySelector("#wizard-niche-popular").value === "true" ? 1 : 0;
  const secondWave = state.wizardMode === "channels" ? Number(document.querySelector("#wizard-second-wave").value) || 0 : 0;
  const units = searches * 100 + 5 + popular + secondWave * 100;
  document.querySelector("#wizard-quota-estimate").innerHTML = `<span>QUOTA STIMATA PREVIEW</span><strong>~${compact.format(units)} unità</strong><small>${searches} ricerche seed${secondWave ? ` · ${secondWave} seconda ondata` : ""}</small>`;
}

function updateWizardMode() {
  state.wizardMode = document.querySelector('input[name="wizard-mode"]:checked').value;
  const panorama = state.wizardMode === "channels";
  document.querySelectorAll("[data-panorama-only]").forEach((element) => element.hidden = !panorama);
  document.querySelectorAll("[data-channel-filter]").forEach((element) => element.hidden = !panorama);
  document.querySelectorAll("[data-video-filter]").forEach((element) => element.hidden = panorama);
  document.querySelector("#wizard-video-options").hidden = panorama;
  document.querySelector("#panorama-facets").hidden = !panorama || !state.wizardPreview.length;
  document.querySelector("#wizard-preview-title").textContent = panorama ? "Seleziona i canali" : "Seleziona i contenuti";
  document.querySelector("#wizard-preview-hint").textContent = panorama
    ? "Esplora score, temi e cerchi. I filtri qui sotto non consumano quota."
    : "Filtra e scegli i video da importare nel progetto. Solo i selezionati verranno acquisiti.";
  document.querySelector("#preview-search").textContent = panorama ? "Genera panorama" : "Cerca candidati";
  updateWizardQuotaEstimate();
}

async function startWizard(projectId = null, step = 1) {
  state.wizardProjectId = projectId;
  state.wizardStep = step;
  state.wizardNicheId = null;
  state.wizardJobId = null;
  state.wizardPreview = [];
  state.wizardPreviewStats = null;
  state.wizardCircles = [];
  state.wizardPoolThemes = [];
  state.wizardSelected.clear();
  document.querySelector("#wizard-error").textContent = "";
  document.querySelector("#wizard-project-name").value = "";
  document.querySelector("#wizard-project-description").value = "";
  document.querySelector("#wizard-niche-name").value = "";
  document.querySelector("#wizard-niche-description").value = "";
  document.querySelector("#wizard-niche-channels").value = "";
  document.querySelector("#wizard-niche-videos").value = "";
  document.querySelector("#wizard-niche-include").value = "";
  document.querySelector("#wizard-niche-exclude").value = "";
  document.querySelector("#wizard-mode-videos").checked = true;
  state.wizardMode = "videos";
  document.querySelector("#wizard-niche-days").value = "90";
  document.querySelector("#wizard-niche-max-results").value = "200";
  document.querySelector("#wizard-niche-min-views").value = "0";
  document.querySelector("#wizard-niche-region").value = "";
  document.querySelector("#wizard-niche-language").value = "";
  document.querySelector("#wizard-niche-min-subs").value = "0";
  document.querySelector("#wizard-niche-max-subs").value = "";
  document.querySelector("#wizard-niche-popular").value = "false";
  document.querySelector("#wizard-niche-strict").value = "false";
  document.querySelector("#wizard-niche-top-channels").value = "false";
  document.querySelector("#wizard-evidence-depth").value = "P2";
  document.querySelector("#wizard-second-wave").value = "0";
  document.querySelector("#wizard-cross-theme").checked = false;
  const defaultWeights = { theme: 1, geo: 0.5, size: 0.3, popularity: 0.3, engagement: 0.5, velocity: 0.4 };
  Object.entries(defaultWeights).forEach(([name, value]) => document.querySelector(`#wizard-weight-${name}`).value = String(value));
  document.querySelector("#preview-min-views").value = "0";
  document.querySelector("#preview-min-score").value = "0";
  ["#preview-min-subs", "#preview-channel-min-views"].forEach((selector) => document.querySelector(selector).value = "0");
  ["#preview-max-subs", "#preview-channel-max-views", "#preview-themes-include", "#preview-themes-exclude"].forEach((selector) => document.querySelector(selector).value = "");
  document.querySelector("#preview-promoted-only").checked = false;
  document.querySelector("#preview-text-filter").value = "";
  document.querySelector("#wizard-preview-table").innerHTML = `<p class="empty">Clicca "Cerca candidati" per vedere i video trovati dai seed.</p>`;
  document.querySelector("#wizard-populate-comments").value = "true";
  document.querySelector("#wizard-populate-max-videos").value = "5";
  document.querySelector("#wizard-populate-comments-per-video").value = "50";
  document.querySelector("#wizard-job-status").innerHTML = "";
  updateWizardMode();
  updateSelectionCount();
  if (projectId) {
    const project = state.projects.find((p) => p.id === projectId);
    document.querySelector("#wizard-title").textContent = project ? `Popola ${escapeHtml(project.name)}` : "Popola il progetto";
  } else {
    document.querySelector("#wizard-title").textContent = "Crea il tuo progetto";
  }
  showView("wizard");
  renderWizardStep();
}

function renderWizardStep() {
  const step = state.wizardStep;
  const panorama = state.wizardMode === "channels";
  document.querySelectorAll(".wizard-step").forEach((el) => el.hidden = Number(el.dataset.step) !== step);
  document.querySelectorAll(".wizard-steps span").forEach((el) => el.classList.toggle("active", Number(el.dataset.step) === step));
  const back = document.querySelector("#wizard-back");
  const next = document.querySelector("#wizard-next");
  back.hidden = false;
  if (step === 1) back.textContent = state.wizardProjectId ? "Torna ai progetti" : "Annulla";
  else back.textContent = "Indietro";
  if (step === 3) next.textContent = panorama ? "Configura bacino" : "Conferma selezione";
  else if (step === 4) next.textContent = state.wizardJobId ? "Vai alla dashboard" : "Avvia acquisizione";
  else next.textContent = "Avanti";
  next.hidden = panorama && step === 4 && !state.wizardJobId;
  const materializeActions = document.querySelector("#wizard-materialize-actions");
  materializeActions.hidden = !panorama || step !== 4 || Boolean(state.wizardJobId);
  document.querySelector("#materialize-curated").disabled = state.wizardSelected.size === 0;
  document.querySelector("#wizard-final-title").textContent = panorama ? "Materializza il panorama" : "Acquisizione in corso";
  document.querySelector("#wizard-final-hint").textContent = panorama
    ? "Scegli un bacino curato oppure regole dinamiche da rivalutare nel tempo."
    : "I contenuti selezionati vengono salvati e, se abilitato, i commenti acquisiti e analizzati.";
  if (step === 4) renderWizardSummary();
}

function renderWizardSummary() {
  const projectName = state.wizardProjectId
    ? (state.projects.find((p) => p.id === state.wizardProjectId)?.name || "Progetto esistente")
    : document.querySelector("#wizard-project-name").value.trim() || "Nuovo progetto";
  const nicheName = document.querySelector("#wizard-niche-name").value.trim() || "—";
  const channels = document.querySelector("#wizard-niche-channels").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const videos = document.querySelector("#wizard-niche-videos").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const keywords = document.querySelector("#wizard-niche-include").value.split(",").map((s) => s.trim()).filter(Boolean);
  const geo = geoFilters("wizard-niche");
  const geoParts = [];
  if (geo.region_code) geoParts.push(`regione ${geo.region_code}`);
  if (geo.relevance_language) geoParts.push(`lingua ${geo.relevance_language}`);
  if (geo.min_subscribers) geoParts.push(`min ${compact.format(geo.min_subscribers)} iscritti`);
  if (geo.harvest_popular) geoParts.push("popolari regionali");
  if (geo.strict_geo) geoParts.push("perimetro rigido");
  const autoComments = document.querySelector("#wizard-populate-comments").value === "true";
  const panorama = state.wizardMode === "channels";
  document.querySelector("#wizard-summary").innerHTML = `
    <h3>Riepilogo</h3>
    <dl>
      <dt>PROGETTO</dt><dd>${escapeHtml(projectName)}</dd>
      <dt>NICCHIA</dt><dd>${escapeHtml(nicheName)}</dd>
      <dt>CANALI SEME</dt><dd>${channels.length ? escapeHtml(channels.join(", ")) : "—"}</dd>
      <dt>VIDEO SEME</dt><dd>${videos.length ? escapeHtml(videos.join(", ")) : "—"}</dd>
      <dt>KEYWORD</dt><dd>${keywords.length ? escapeHtml(keywords.join(", ")) : "—"}</dd>
      <dt>PERIMETRO GEO</dt><dd>${geoParts.length ? escapeHtml(geoParts.join(" · ")) : "—"}</dd>
      <dt>MODALITÀ</dt><dd>${panorama ? "Panorama canali" : "Video"}</dd>
      <dt>SELEZIONATI</dt><dd>${state.wizardSelected.size} ${panorama ? "canali" : "contenuti"}</dd>
      ${panorama ? `<dt>PROFONDITÀ</dt><dd>${escapeHtml(document.querySelector("#wizard-evidence-depth").value)} · ${state.wizardCircles.length} cerchi emergenti</dd>` : `<dt>COMMENTI AUTO</dt><dd>${autoComments ? "Sì" : "No"}</dd>`}
    </dl>`;
}

function validateWizardStep(step) {
  if (step === 1 && !state.wizardProjectId) {
    const name = document.querySelector("#wizard-project-name").value.trim();
    if (!name) return "Inserisci un nome per il progetto.";
  }
  if (step === 2) {
    const name = document.querySelector("#wizard-niche-name").value.trim();
    if (!name) return "Inserisci un nome per la nicchia.";
    const channels = document.querySelector("#wizard-niche-channels").value.split("\n").map((s) => s.trim()).filter(Boolean);
    const videos = document.querySelector("#wizard-niche-videos").value.split("\n").map((s) => s.trim()).filter(Boolean);
    const keywords = document.querySelector("#wizard-niche-include").value.split(",").map((s) => s.trim()).filter(Boolean);
    const geo = geoFilters("wizard-niche");
    const regionalPopular = geo.harvest_popular && geo.region_code;
    if (!channels.length && !videos.length && !keywords.length && !regionalPopular) return "Inserisci almeno un canale, un video, una keyword oppure attiva i popolari regionali.";
  }
  if (step === 3 && state.wizardMode === "videos" && state.wizardSelected.size === 0) {
    return "Seleziona almeno un contenuto dalla preview.";
  }
  return null;
}

async function advanceWizard() {
  const errorEl = document.querySelector("#wizard-error");
  errorEl.textContent = "";
  const error = validateWizardStep(state.wizardStep);
  if (error) { errorEl.textContent = error; return; }
  if (state.wizardStep === 1) {
    if (!state.wizardProjectId) {
      const response = await fetch("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: document.querySelector("#wizard-project-name").value.trim(), description: document.querySelector("#wizard-project-description").value.trim() }),
      });
      const result = await response.json();
      if (!response.ok) { errorEl.textContent = result.detail || "Creazione progetto non riuscita."; return; }
      state.wizardProjectId = result.id;
      state.projectId = result.id;
      await loadProjects(result.id, false);
    }
    state.wizardStep = 2;
  } else if (state.wizardStep === 2) {
    const response = await fetch("/api/niches", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.wizardProjectId,
        name: document.querySelector("#wizard-niche-name").value.trim(),
        description: document.querySelector("#wizard-niche-description").value.trim(),
        status: "active",
        kind: state.wizardMode === "channels" ? "panorama" : "topic",
        definition: { preview_mode: state.wizardMode },
        seed_channels: document.querySelector("#wizard-niche-channels").value.split("\n").map((s) => s.trim()).filter(Boolean).map((value) => ({ channel_id: value, channel_title: value })),
        seed_videos: document.querySelector("#wizard-niche-videos").value.split("\n").map((s) => s.trim()).filter(Boolean).map((value) => ({ video_id: value, title: value })),
        include_keywords: document.querySelector("#wizard-niche-include").value.split(",").map((s) => s.trim()).filter(Boolean),
        exclude_keywords: document.querySelector("#wizard-niche-exclude").value.split(",").map((s) => s.trim()).filter(Boolean),
        filters: wizardCollectionFilters(),
      }),
    });
    const result = await response.json();
    if (!response.ok) { errorEl.textContent = result.detail || "Creazione nicchia non riuscita."; return; }
    state.wizardNicheId = result.id;
    state.wizardStep = 3;
    state.wizardPreview = [];
    state.wizardSelected.clear();
    updateSelectionCount();
    document.querySelector("#wizard-preview-table").innerHTML = `<p class="empty">${state.wizardMode === "channels" ? "Genera il panorama per vedere i canali trovati." : "Clicca \"Cerca candidati\" per vedere i video trovati dai seed."}</p>`;
  } else if (state.wizardStep === 3) {
    state.wizardStep = 4;
  } else if (state.wizardStep === 4) {
    if (state.wizardJobId) {
      openProject(state.wizardProjectId);
      return;
    }
    await populateWizard();
  }
  renderWizardStep();
}

function goBackWizard() {
  if (state.wizardStep === 1) {
    openProjectHub();
    return;
  }
  state.wizardStep -= 1;
  renderWizardStep();
}

function updateSelectionCount() {
  document.querySelector("#preview-selection-count").textContent = `${state.wizardSelected.size} ${state.wizardMode === "channels" ? "canali" : "contenuti"} selezionati`;
}

function previewItemId(item) {
  return state.wizardMode === "channels" ? item.channel_id : item.external_id;
}

function getFilteredPreview() {
  const minScore = Number(document.querySelector("#preview-min-score").value) || 0;
  const text = document.querySelector("#preview-text-filter").value.trim().toLowerCase();
  const channelFilters = state.wizardMode === "channels" ? wizardClientFilters() : null;
  return state.wizardPreview.filter((item) => {
    if (channelFilters) {
      const subscribers = item.subscribers || 0;
      const views = item.avg_views || 0;
      const themes = (item.themes || []).map((theme) => String(theme.term || theme).toLowerCase());
      if (subscribers < channelFilters.min_subscribers || (channelFilters.max_subscribers && subscribers > channelFilters.max_subscribers)) return false;
      if (views < channelFilters.min_views || (channelFilters.max_views && views > channelFilters.max_views)) return false;
      if ((item.score || 0) < minScore || (channelFilters.promoted_only && !item.promoted)) return false;
      if (channelFilters.themes_include.length && !channelFilters.themes_include.every((term) => themes.some((theme) => theme.includes(term)))) return false;
      if (channelFilters.themes_exclude.some((term) => themes.some((theme) => theme.includes(term)))) return false;
    } else {
      if ((item.views || 0) < (Number(document.querySelector("#preview-min-views").value) || 0)) return false;
      if ((item.relevance_score || 0) < minScore) return false;
    }
    if (text) {
      const haystack = `${item.title || ""} ${item.channel_title || ""} ${item.description || ""} ${item.matched_value || ""} ${(item.themes || []).map((theme) => theme.term || theme).join(" ")} ${(item.circles || []).join(" ")}`.toLowerCase();
      if (!haystack.includes(text)) return false;
    }
    return true;
  });
}

function renderPanoramaFacets() {
  const target = document.querySelector("#panorama-facets");
  if (state.wizardMode !== "channels" || !state.wizardPreview.length) {
    target.hidden = true;
    return;
  }
  target.hidden = false;
  const themes = state.wizardPoolThemes.slice(0, 12).map((theme) => `<span>${escapeHtml(theme.term)} <b>${theme.channels}</b></span>`).join("");
  const circles = state.wizardCircles.slice(0, 8).map((circle) => `<span class="circle-chip">${escapeHtml(circle.label)}</span>`).join("");
  target.innerHTML = `<div><small>TEMI DEL POOL</small>${themes || "—"}</div><div><small>CERCHI EMERGENTI</small>${circles || "—"}</div>`;
}

function renderPreviewTable() {
  const table = document.querySelector("#wizard-preview-table");
  const filtered = getFilteredPreview();
  const stats = state.wizardPreviewStats
    ? `${previewStatsHtml(state.wizardPreviewStats)}<p class="preview-elapsed">Ricerca completata in ${state.wizardPreviewStats.seconds}s · ${state.wizardPreview.length} candidati</p>`
    : "";
  if (!state.wizardPreview.length) {
    table.innerHTML = stats || `<p class="empty">${state.wizardMode === "channels" ? "Genera il panorama per vedere i canali trovati." : "Clicca \"Cerca candidati\" per vedere i video trovati dai seed."}</p>`;
    if (stats) table.innerHTML += `<p class="empty">Nessun candidato trovato. Controlla la diagnostica delle fonti qui sopra.</p>`;
    return;
  }
  if (!filtered.length) {
    table.innerHTML = `${stats}<p class="empty">Nessun candidato corrisponde ai filtri.</p>`;
    return;
  }
  if (state.wizardMode === "channels") {
    table.innerHTML = `${stats}
      <table class="channel-preview-table">
        <thead><tr><th><input type="checkbox" id="preview-toggle-all" ${filtered.every((item) => state.wizardSelected.has(item.channel_id)) ? "checked" : ""}></th><th>Canale</th><th>Temi e cerchi</th><th>Iscritti</th><th>Views medie</th><th>Score</th></tr></thead>
        <tbody>${filtered.map((item) => {
          const breakdown = Object.entries(item.score_breakdown || {}).map(([name, value]) => `<span>${escapeHtml(name)} <b>${Number(value).toFixed(2)}</b></span>`).join("");
          const themes = (item.themes || []).slice(0, 5).map((theme) => `<span>${escapeHtml(theme.term || theme)}</span>`).join("");
          const circles = (item.circles || []).slice(0, 3).map((circle) => `<span class="circle-chip">${escapeHtml(circle)}</span>`).join("");
          return `<tr data-preview-id="${escapeHtml(item.channel_id)}">
            <td data-label="Seleziona"><input type="checkbox" class="preview-checkbox" data-id="${escapeHtml(item.channel_id)}" ${state.wizardSelected.has(item.channel_id) ? "checked" : ""}></td>
            <td data-label="Canale"><span class="preview-title">${escapeHtml(item.channel_title || item.channel_id)}</span><span class="preview-channel">${escapeHtml([item.country, item.language, item.promoted ? "promosso" : ""].filter(Boolean).join(" · "))}</span></td>
            <td data-label="Temi"><div class="channel-themes">${themes || "—"}${circles}</div></td>
            <td data-label="Iscritti"><span class="preview-views">${compact.format(item.subscribers || 0)}</span></td>
            <td data-label="Views medie"><span class="preview-views">${compact.format(item.avg_views || 0)}</span></td>
            <td data-label="Score"><span class="preview-score">${Number(item.score || 0).toFixed(3)}</span><details class="score-breakdown"><summary>breakdown</summary><div>${breakdown}</div></details></td>
          </tr>`;
        }).join("")}</tbody>
      </table>`;
    renderPanoramaFacets();
    return;
  }
  table.innerHTML = `${stats}
    <table>
      <thead><tr>
         <th style="width:30px"><input type="checkbox" id="preview-toggle-all" ${filtered.length > 0 && filtered.every((item) => state.wizardSelected.has(previewItemId(item))) ? "checked" : ""}></th>
        <th>Video</th>
        <th style="width:90px">Score</th>
        <th style="width:90px">Views</th>
        <th style="width:110px">Seed</th>
      </tr></thead>
      <tbody>
        ${filtered.map((item) => {
          const channelMeta = [item.channel_title || item.channel_id || "—"];
          if (item.channel_subscribers) channelMeta.push(`${compact.format(item.channel_subscribers)} iscritti`);
          const geoTag = [item.channel_country, item.channel_language].filter(Boolean).join("/");
          if (geoTag) channelMeta.push(geoTag);
          return `
          <tr data-preview-id="${item.external_id}">
            <td><input type="checkbox" class="preview-checkbox" data-id="${item.external_id}" ${state.wizardSelected.has(item.external_id) ? "checked" : ""}></td>
            <td><span class="preview-title">${escapeHtml(item.title)}</span><span class="preview-channel">${escapeHtml(channelMeta.join(" · "))}</span></td>
            <td><span class="preview-score">${item.relevance_score}</span></td>
            <td><span class="preview-views">${compact.format(item.views || 0)}</span></td>
            <td><span class="preview-seed">${escapeHtml(item.matched_seed)}</span><small>${escapeHtml(item.matched_value || "")}</small></td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function previewStatsHtml(stats) {
  if (!stats || !stats.sources) return "";
  const labels = { popular: "popolari", channel: "canale", keyword: "keyword", video: "video seme" };
  const parts = stats.sources.map((source) => `${labels[source.type] || source.type} "${escapeHtml(source.value)}": ${source.found}`);
  const warnings = [];
  (stats.unresolved_channels || []).forEach((ref) => {
    warnings.push(`Il canale "${escapeHtml(ref)}" non è stato risolto: usa l'ID canale (UC...), l'handle (@nome) o l'URL del canale.`);
  });
  (stats.invalid_video_seeds || []).forEach((ref) => {
    warnings.push(`Il video seme "${escapeHtml(ref)}" non è un URL o ID video valido ed è stato ignorato.`);
  });
  stats.sources.filter((source) => source.found === 0).forEach((source) => {
    if (source.type === "channel") {
      warnings.push(`Il canale "${escapeHtml(source.value)}" non ha prodotto risultati: verifica che sia l'ID canale (UC...) e che abbia video recenti nella finestra.`);
    } else if (source.type === "keyword") {
      warnings.push(`La keyword "${escapeHtml(source.value)}" non ha prodotto risultati nella finestra temporale.`);
    } else {
      warnings.push(`La fonte "${escapeHtml(source.value)}" non ha prodotto risultati.`);
    }
  });
  if (stats.excluded_geo) warnings.push(`${stats.excluded_geo} contenuti esclusi dal perimetro geo-linguistico o dalla fascia iscritti.`);
  if (stats.sources_skipped && stats.sources_skipped.length) warnings.push(`${stats.sources_skipped.length} fonti oltre il budget di 10 ricerche non sono state eseguite.`);
  return `<div class="preview-stats"><span>${parts.join(" · ")}</span>${warnings.map((w) => `<small>${w}</small>`).join("")}</div>`;
}

async function searchPreview() {
  const errorEl = document.querySelector("#wizard-error");
  errorEl.textContent = "";
  const table = document.querySelector("#wizard-preview-table");
  const button = document.querySelector("#preview-search");
  button.disabled = true;
  table.innerHTML = `<p class="empty">${state.wizardMode === "channels" ? "Costruzione del panorama" : "Ricerca candidati"} in corso: le chiamate API YouTube possono richiedere alcune decine di secondi...</p>`;
  const started = Date.now();
  let result = null;
  let ok = false;
  try {
    const response = await fetch(`/api/niches/${state.wizardNicheId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: state.wizardMode, filters: wizardCollectionFilters() }),
    });
    ok = response.ok;
    try {
      result = await response.json();
    } catch (parseError) {
      result = null;
    }
  } catch (networkError) {
    result = null;
  }
  button.disabled = false;
  if (!ok || !result) {
    errorEl.textContent = (result && result.detail) || "Preview non riuscita: errore di rete o del server.";
    table.innerHTML = `<p class="empty">Errore durante la ricerca.</p>`;
    return;
  }
  const seconds = Math.round((Date.now() - started) / 1000);
  state.wizardPreview = state.wizardMode === "channels" ? (result.channels || []) : (result.items || []);
  state.wizardCircles = result.circles || [];
  state.wizardPoolThemes = result.pool_themes || [];
  state.wizardPreviewStats = { ...(result.stats || {}), seconds };
  state.wizardSelected = new Set(state.wizardPreview.map(previewItemId));
  renderPreviewTable();
  updateSelectionCount();
}

async function populateWizard() {
  const errorEl = document.querySelector("#wizard-error");
  errorEl.textContent = "";
  const response = await fetch(`/api/niches/${state.wizardNicheId}/populate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content_ids: Array.from(state.wizardSelected),
      auto_fetch_comments: document.querySelector("#wizard-populate-comments").value === "true",
      max_comment_videos: Number(document.querySelector("#wizard-populate-max-videos").value),
      comments_per_video: Number(document.querySelector("#wizard-populate-comments-per-video").value),
      include_replies: false,
    }),
  });
  const result = await response.json();
  if (!response.ok) { errorEl.textContent = result.detail || "Avvio acquisizione non riuscito."; return; }
  state.wizardJobId = result.job.id;
  pollWizardJob(result.job.id);
}

async function materializeWizard(membershipMode) {
  const errorEl = document.querySelector("#wizard-error");
  errorEl.textContent = "";
  if (membershipMode === "curated" && state.wizardSelected.size === 0) {
    errorEl.textContent = "Seleziona almeno un canale per creare un bacino curato.";
    return;
  }
  document.querySelectorAll("#wizard-materialize-actions button").forEach((button) => button.disabled = true);
  const response = await fetch(`/api/niches/${state.wizardNicheId}/materialize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      channel_ids: Array.from(state.wizardSelected),
      membership_mode: membershipMode,
      definition: { preview_mode: "channels", selection_filters: wizardClientFilters() },
      filters: wizardCollectionFilters(),
    }),
  });
  let result = null;
  try { result = await response.json(); } catch (parseError) { result = null; }
  if (!response.ok || !result) {
    errorEl.textContent = result?.detail || "Materializzazione non riuscita.";
    document.querySelectorAll("#wizard-materialize-actions button").forEach((button) => button.disabled = false);
    renderWizardStep();
    return;
  }
  state.wizardJobId = result.job.id;
  pollWizardJob(result.job.id, "Materializzazione canali");
}

async function pollWizardJob(jobId, activityLabel = "Acquisizione contenuti") {
  const jobStatus = document.querySelector("#wizard-job-status");
  jobStatus.innerHTML = `<article class="job-row running"><div><span>${activityLabel}</span><strong>in coda</strong></div><i><b style="width:0%"></b></i><small>0%</small></article>`;
  renderWizardStep();
  const interval = window.setInterval(async () => {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) return;
    const job = await response.json();
    const label = { queued: "in coda", running: "in corso", completed: "completato", failed: "fallito", cancelled: "annullato" }[job.status] || job.status;
    jobStatus.innerHTML = `<article class="job-row ${job.status}"><div><span>${activityLabel}</span><strong>${label}</strong></div><i><b style="width:${job.progress}%"></b></i><small>${job.progress}%</small>${job.error ? `<p>${escapeHtml(job.error)}</p>` : ""}</article>`;
    if (["completed", "failed", "cancelled"].includes(job.status)) {
      window.clearInterval(interval);
      if (job.status === "completed") {
        if (state.wizardMode === "channels") {
          const channelsResponse = await fetch(`/api/niches/${state.wizardNicheId}/channels`);
          if (channelsResponse.ok) {
            const membership = await channelsResponse.json();
            jobStatus.innerHTML += `<p class="materialize-result">Bacino creato: ${membership.total} canali materializzati.</p>`;
          }
        }
        renderWizardStep();
      }
    }
  }, 1500);
}

document.querySelector("#open-project-hub").addEventListener("click", openProjectHub);
document.querySelector("#header-projects").addEventListener("click", openProjectHub);
document.querySelector("#hub-new-project").addEventListener("click", () => startWizard(null, 1));
document.querySelector("#project-hub-grid").addEventListener("click", async (event) => {
  const openButton = event.target.closest("[data-open-project]");
  const deleteButton = event.target.closest("[data-delete-project]");
  if (openButton) {
    openProject(Number(openButton.dataset.openProject));
    return;
  }
  if (deleteButton) {
    await deleteProjectFromHub(Number(deleteButton.dataset.deleteProject));
  }
});
document.querySelector("#wizard-next").addEventListener("click", advanceWizard);
document.querySelector("#wizard-back").addEventListener("click", goBackWizard);
document.querySelector("#preview-search").addEventListener("click", searchPreview);
document.querySelectorAll('input[name="wizard-mode"]').forEach((input) => input.addEventListener("change", updateWizardMode));
document.querySelector("#materialize-curated").addEventListener("click", () => materializeWizard("curated"));
document.querySelector("#materialize-rule-based").addEventListener("click", () => materializeWizard("rule_based"));
document.querySelector("#preview-select-all").addEventListener("click", () => {
  getFilteredPreview().forEach((item) => state.wizardSelected.add(previewItemId(item)));
  renderPreviewTable();
  updateSelectionCount();
});
document.querySelector("#preview-deselect-all").addEventListener("click", () => {
  getFilteredPreview().forEach((item) => state.wizardSelected.delete(previewItemId(item)));
  renderPreviewTable();
  updateSelectionCount();
});
["#preview-min-views", "#preview-min-score", "#preview-text-filter", "#preview-min-subs", "#preview-max-subs", "#preview-channel-min-views", "#preview-channel-max-views", "#preview-themes-include", "#preview-themes-exclude", "#preview-promoted-only"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", () => {
    renderPreviewTable();
  });
});
document.querySelector("#wizard-preview-table").addEventListener("change", (event) => {
  const toggle = event.target.closest("#preview-toggle-all");
  const checkbox = event.target.closest(".preview-checkbox");
  if (toggle) {
    const filtered = getFilteredPreview();
    if (toggle.checked) filtered.forEach((item) => state.wizardSelected.add(previewItemId(item)));
    else filtered.forEach((item) => state.wizardSelected.delete(previewItemId(item)));
  } else if (checkbox) {
    const id = checkbox.dataset.id;
    if (checkbox.checked) state.wizardSelected.add(id);
    else state.wizardSelected.delete(id);
  }
  renderPreviewTable();
  updateSelectionCount();
});

["#wizard-niche-channels", "#wizard-niche-include", "#wizard-niche-popular", "#wizard-second-wave"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", updateWizardQuotaEstimate);
});

document.querySelector("#new-project").addEventListener("click", () => startWizard(null, 1));
document.querySelector("#onboarding-create-niche").addEventListener("click", () => startWizard(state.projectId, 2));
document.querySelector("#hub-new-project-empty").addEventListener("click", () => startWizard(null, 1));

async function initializeApp() {
  try {
    await loadUser();
    await loadProjects(null, true);
    if (state.view === "dashboard") {
      await Promise.allSettled([loadNiches(), loadSources(), loadMonitoring(), loadJobs(), loadSourcesList(), loadAllReports(), loadAdvReport(), loadEntities()]);
      window.setInterval(loadJobs, 2000);
    }
  } catch (error) {
    document.querySelector("#metrics").innerHTML = empty(error.message);
  }
}

initializeApp().catch((error) => {
  document.querySelector("#metrics").innerHTML = empty(error.message);
});
