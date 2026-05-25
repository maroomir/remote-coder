(function (window) {
  function _escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  async function _parseApiError(r, rawText) {
    var ct = (r.headers.get("content-type") || "").toLowerCase();
    if (ct.includes("application/json")) {
      try {
        var j = JSON.parse(rawText);
        if (j && typeof j.detail === "string") return j.detail;
        if (Array.isArray(j.detail)) {
          return j.detail.map(function (d) {
            return typeof d.msg === "string" ? d.msg : JSON.stringify(d);
          }).join("\n");
        }
      } catch (_) { /* ignore */ }
    }
    return rawText || "Request failed (" + r.status + ")";
  }

  function renderSummaryGrid(settings, projectsPayload) {
    var grid = document.getElementById("summary-grid");
    if (!grid) return;
    var list = projectsPayload.projects || [];
    var enabled = list.filter(function (p) { return p.enabled; }).length;
    var defName = projectsPayload.default_project || window.i18n.t("common.none");
    var envModel = settings.default_model_env || "—";
    var timeout = settings.job_timeout_seconds_env != null
      ? String(settings.job_timeout_seconds_env) + window.i18n.t("common.secondsSuffix")
      : "—";
    var tokenOk = settings.telegram_bot_token_masked &&
      settings.telegram_bot_token_masked !== "(not set)";

    grid.innerHTML =
      '<div class="stat-card"><p class="label">' + _escapeHtml(window.i18n.t("summary.registered")) + '</p><p class="value">' + list.length + "</p></div>" +
      '<div class="stat-card"><p class="label">' + _escapeHtml(window.i18n.t("summary.active")) + '</p><p class="value">' + enabled + "</p></div>" +
      '<div class="stat-card"><p class="label">' + _escapeHtml(window.i18n.t("common.fallbackDefault")) + '</p><p class="value" style="font-size:1rem">' + _escapeHtml(defName) + "</p></div>" +
      '<div class="stat-card"><p class="label">' + _escapeHtml(window.i18n.t("summary.envModel")) + '</p><p class="value" style="font-size:1rem">' + _escapeHtml(envModel) + "</p></div>" +
      '<div class="stat-card"><p class="label">' + _escapeHtml(window.i18n.t("summary.envTimeout")) + '</p><p class="value" style="font-size:1rem">' + _escapeHtml(timeout) + "</p></div>" +
      '<div class="stat-card"><p class="label">' + _escapeHtml(window.i18n.t("summary.botToken")) + '</p><p class="value" style="font-size:0.95rem">' +
        (tokenOk ? _escapeHtml(window.i18n.t("common.set")) : _escapeHtml(window.i18n.t("common.unset"))) +
      '</p><p class="sub">' + _escapeHtml(window.i18n.tv(settings.telegram_bot_token_masked || "")) + "</p></div>";
  }

  async function loadSummaryGrid(onError) {
    try {
      var rs = await fetch("/api/settings");
      var rp = await fetch("/api/projects");
      var settingsText = await rs.text();
      var projectsText = await rp.text();
      if (!rs.ok) {
        if (onError) onError(await _parseApiError(rs, settingsText));
        return { ok: false };
      }
      if (!rp.ok) {
        if (onError) onError(await _parseApiError(rp, projectsText));
        return { ok: false };
      }
      var settings = JSON.parse(settingsText);
      var projectsPayload = JSON.parse(projectsText);
      renderSummaryGrid(settings, projectsPayload);
      return { ok: true, settings: settings, projectsPayload: projectsPayload };
    } catch (e) {
      if (onError) onError(String(e));
      return { ok: false };
    }
  }

  window.adminSummary = { renderSummaryGrid: renderSummaryGrid, loadSummaryGrid: loadSummaryGrid };
})(window);
