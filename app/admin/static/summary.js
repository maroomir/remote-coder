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
    return rawText || "요청 실패 (" + r.status + ")";
  }

  function renderSummaryGrid(settings, projectsPayload) {
    var grid = document.getElementById("summary-grid");
    if (!grid) return;
    var list = projectsPayload.projects || [];
    var enabled = list.filter(function (p) { return p.enabled; }).length;
    var defName = projectsPayload.default_project || "(없음)";
    var envModel = settings.default_model_env || "—";
    var timeout = settings.job_timeout_seconds_env != null
      ? String(settings.job_timeout_seconds_env) + "초"
      : "—";
    var tokenOk = settings.telegram_bot_token_masked &&
      settings.telegram_bot_token_masked !== "(설정 안 됨)";

    grid.innerHTML =
      '<div class="stat-card"><p class="label">등록 프로젝트</p><p class="value">' + list.length + "</p></div>" +
      '<div class="stat-card"><p class="label">활성</p><p class="value">' + enabled + "</p></div>" +
      '<div class="stat-card"><p class="label">폴백 기본</p><p class="value" style="font-size:1rem">' + _escapeHtml(defName) + "</p></div>" +
      '<div class="stat-card"><p class="label">환경 기본 모델</p><p class="value" style="font-size:1rem">' + _escapeHtml(envModel) + "</p></div>" +
      '<div class="stat-card"><p class="label">환경 타임아웃</p><p class="value" style="font-size:1rem">' + _escapeHtml(timeout) + "</p></div>" +
      '<div class="stat-card"><p class="label">봇 토큰</p><p class="value" style="font-size:0.95rem">' +
        (tokenOk ? "설정됨" : "미설정") +
      '</p><p class="sub">' + _escapeHtml(settings.telegram_bot_token_masked || "") + "</p></div>";
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
