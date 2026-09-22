/* REvoCompute — Profile settings page */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  var A = window.REvoDesignAuth;
  var T = window.REvoDesignTheme;
  var UI = window.REvoComputeUI;

  var infoEl = document.getElementById("userInfo");
  var POSITION_LABELS = UI.positionLabels;
  var ROLE_LABELS = { admin: "Administrator", user: "User", guest: "Guest account" };

  T.initToggle(document.getElementById("themeToggle"));

  /* ---- Section navigation ----
     One active section at a time. Sections are reachable by URL hash so a
     link survives reload, and the shared .sub-tabs primitive is the same
     control on desktop (sidebar list) and narrow screens (wrapping tabs). */

  var tabs = Array.prototype.slice.call(document.querySelectorAll("#profileTabs .sub-tab"));
  var sections = {};
  tabs.forEach(function (tab) { sections[tab.dataset.section] = document.getElementById("section-" + tab.dataset.section); });

  function activateSection(name) {
    var next = sections[name] || sections.profile;
    name = next.dataset.section;
    // The URL is the router's own state: keep it pointing at the section that
    // actually activated, so a bookmarked link and the visible panel agree.
    if (location.hash.slice(1) !== name) location.hash = name;
    tabs.forEach(function (tab) {
      var active = tab.dataset.section === name;
      tab.classList.toggle("active", active);
      if (active) tab.setAttribute("aria-current", "true");
      else tab.removeAttribute("aria-current");
    });
    Object.keys(sections).forEach(function (key) { sections[key].hidden = key !== name; });
    next.classList.remove("layout-transition");
    void next.offsetWidth; /* restart the shared transition on each switch */
    next.classList.add("layout-transition");
  }

  /* Guest accounts have no password and no API key: the server refuses both
     call chains. Remove the sections entirely so neither a click nor a
     crafted #hash can reach them; an unreachable hash falls back to Profile. */
  function restrictGuestSections() {
    ["security", "api-key"].forEach(function (name) {
      if (sections[name]) sections[name].remove();
      delete sections[name];
    });
    tabs = tabs.filter(function (tab) {
      if (tab.dataset.section !== "security" && tab.dataset.section !== "api-key") return true;
      tab.remove();
      return false;
    });
    // A guest's hash may name a section they are not allowed to have; rewrite
    // it through the router rather than around it, so the hash and the active
    // section can never disagree.
    activateSection(requestedSection());
  }

  function requestedSection() {
    var name = location.hash.slice(1);
    return sections[name] ? name : "profile";
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      location.hash = tab.dataset.section;
      activateSection(tab.dataset.section);
    });
  });
  window.addEventListener("hashchange", function () { activateSection(requestedSection()); });
  activateSection(requestedSection());

  /* ---- Runner Access ----
     Server-owned policy state projected as a dense state list. The state is
     the primary content; the licence and description stay secondary. */

  var runnerAccessList = document.getElementById("runnerAccessList");
  var accessMessage = document.getElementById("runnerAccessMessage");

  function accessState(policy) {
    if (policy.granted) return "Granted";
    if (policy.expired) return "Expired";
    if (policy.request_status === "pending") return "Pending";
    if (policy.request_status === "rejected") return "Rejected";
    return policy.requestable ? "Requestable" : "Restricted";
  }

  function setAccessMessage(text, isError) {
    if (!accessMessage) {
      accessMessage = document.createElement("p");
      accessMessage.id = "runnerAccessMessage";
      runnerAccessList.before(accessMessage);
    }
    accessMessage.className = isError ? "status-msg error" : "status-msg success";
    accessMessage.textContent = text;
  }

  function clearAccessMessage() {
    if (!accessMessage) return;
    accessMessage.className = "status-msg";
    accessMessage.textContent = "";
  }

  function renderRunnerAccess(policies) {
    clearAccessMessage();
    runnerAccessList.replaceChildren();
    if (!policies || !policies.length) {
      var empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No restricted Runner policies are configured.";
      runnerAccessList.appendChild(empty);
      return;
    }
    policies.forEach(function (policy) {
      var state = accessState(policy);
      var row = document.createElement("article"); row.className = "access-row";

      var summary = document.createElement("div"); summary.className = "access-summary";
      var heading = document.createElement("h3"); heading.className = "access-name";
      heading.textContent = policy.label || policy.policy_id;
      if (policy.license && policy.license.name) {
        var restriction = document.createElement("span"); restriction.className = "access-restriction";
        restriction.textContent = policy.license.name;
        heading.appendChild(restriction);
      }
      var status = document.createElement("span");
      status.className = "status-chip access-state " + state.toLowerCase();
      status.textContent = state;
      summary.append(heading, status);

      var detailText = "";
      if (state === "Granted" && policy.expires_at) {
        detailText = "Valid until " + new Date(policy.expires_at * 1000).toLocaleString();
      } else if (state === "Pending") {
        detailText = "Request submitted — awaiting an administrator decision.";
      } else if (state === "Rejected") {
        detailText = policy.last_decision
          ? "Last decision: " + policy.last_decision
          : "Your request was not approved. Contact the operator if your circumstances changed.";
      } else if (state === "Expired") {
        detailText = "A previous grant expired. Request access again to renew it.";
      }
      var detail = document.createElement("p"); detail.className = "access-detail"; detail.textContent = detailText;
      summary.appendChild(detail);
      row.appendChild(summary);

      if (!policy.granted && policy.requestable && policy.request_status !== "pending") {
        var action = document.createElement("div"); action.className = "access-action";
        var reasonLabel = document.createElement("label"); reasonLabel.className = "access-reason-label";
        reasonLabel.appendChild(document.createTextNode("Research use and affiliation"));
        var reason = document.createElement("textarea"); reason.className = "text-input"; reason.rows = 2;
        reason.maxLength = 1000; reason.required = true;
        reason.placeholder = "Describe the non-commercial research use and your affiliation.";
        reasonLabel.appendChild(reason); action.appendChild(reasonLabel);
        var request = document.createElement("button"); request.className = "btn btn-primary"; request.type = "button"; request.textContent = "Request access";
        request.addEventListener("click", function () {
          var requestReason = reason.value.trim();
          if (!requestReason) {
            setAccessMessage("Describe your research use before requesting access.", true);
            reason.focus();
            return;
          }
          request.disabled = true;
          A.authFetch("/compute/api/access/requests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ policy_id: policy.policy_id, reason: requestReason }) })
            .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
            .then(function (result) { if (!result.ok) throw new Error(result.data.error || "Access request failed."); loadRunnerAccess(); })
            .catch(function (error) { request.disabled = false; setAccessMessage(error.message, true); });
        });
        action.appendChild(request); row.appendChild(action);
      }

      var prose = policy.description || policy.notice;
      var licenseUrl = policy.license && policy.license.url;
      if (prose || licenseUrl) {
        var more = document.createElement("details"); more.className = "access-more";
        var moreSummary = document.createElement("summary"); moreSummary.textContent = "Details";
        more.appendChild(moreSummary);
        var proseText = document.createElement("p");
        proseText.className = "muted";
        proseText.textContent = prose || "Operator verification is required before use.";
        more.appendChild(proseText);
        if (licenseUrl) {
          var link = document.createElement("a"); link.className = "access-license app-link";
          link.href = licenseUrl; link.target = "_blank"; link.rel = "noopener noreferrer";
          link.textContent = (policy.license.name || "Terms of Use") + " ↗";
          more.appendChild(link);
        }
        row.appendChild(more);
      }
      runnerAccessList.appendChild(row);
    });
  }

  function loadRunnerAccess() {
    A.authFetch("/compute/api/access")
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) { renderRunnerAccess(data.policies); })
      .catch(function () { setAccessMessage("Unable to load Runner access.", true); });
  }
  loadRunnerAccess();

  /* ---- GPU Credits (server-owned accounting, projected as-is) ---- */

  var gpuCreditPeriod = document.getElementById("gpuCreditPeriod");
  var gpuCreditAccess = document.getElementById("gpuCreditAccess");
  var gpuCreditHistory = document.getElementById("gpuCreditHistory");

  function formatCredits(value, signed) {
    var number = Number(value || 0);
    var text = number.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return signed && number > 0 ? "+" + text : text;
  }

  function gpuEntryLabel(kind) {
    return {
      monthly_grant: "Monthly allocation",
      usage: "GPU usage",
      admin_adjustment: "Admin adjustment",
      admin_reset: "Administrative reset",
      reversal: "Correction",
      migration_adjustment: "Imported adjustment"
    }[kind] || "Credit activity";
  }

  function renderGpuCredit(data) {
    var period = new Date(data.period + "-01T00:00:00Z");
    gpuCreditPeriod.textContent = period.toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
    gpuCreditAccess.textContent = data.allow_gpu_use ? "GPU access granted" : "GPU access not granted";
    gpuCreditAccess.className = "status-chip " + (data.allow_gpu_use ? "granted" : "restricted");
    document.getElementById("gpuMonthlyAllocation").textContent = formatCredits(data.monthly_grant_credits);
    document.getElementById("gpuAdjustments").textContent = formatCredits(data.adjustment_credits, true);
    document.getElementById("gpuUsed").textContent = formatCredits(data.usage_credits);
    document.getElementById("gpuRemaining").textContent = formatCredits(data.remaining_credits);
    gpuCreditHistory.replaceChildren();
    if (!data.history.length) {
      gpuCreditHistory.innerHTML = '<p class="muted">No activity in this period.</p>';
      return;
    }
    data.history.forEach(function (entry) {
      var row = document.createElement("div"); row.className = "gpu-credit-entry";
      var copy = document.createElement("div");
      var title = document.createElement("strong"); title.textContent = gpuEntryLabel(entry.kind);
      var detail = document.createElement("span");
      detail.textContent = entry.reason || new Date(entry.created_at * 1000).toLocaleString();
      var amount = document.createElement("b");
      amount.textContent = formatCredits(entry.gpu_seconds / 60, true);
      amount.className = entry.gpu_seconds < 0 ? "credit-debit" : "credit-credit";
      copy.append(title, detail); row.append(copy, amount); gpuCreditHistory.appendChild(row);
    });
  }

  A.authFetch("/compute/api/gpu-credit")
    .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
    .then(renderGpuCredit)
    .catch(function () {
      gpuCreditPeriod.textContent = "Unable to load GPU credit accounting.";
      gpuCreditHistory.replaceChildren();
    });

  /* ---- Metrics ----
     Aggregated server-side from persisted Tasks over a bounded window. */

  var metricsWindow = document.getElementById("metricsWindow");
  var metricsPeriod = document.getElementById("metricsPeriod");
  var metricsEmpty = document.getElementById("metricsEmpty");
  var metricsComposition = document.getElementById("metricsComposition");
  var metricsActivity = document.getElementById("metricsActivity");
  var metricsDistribution = document.getElementById("metricsDistribution");

  function formatRuntime(seconds) {
    if (seconds == null) return "—";
    if (seconds < 60) return Math.round(seconds) + "s";
    if (seconds < 3600) return Math.round(seconds / 60) + "m";
    if (seconds < 86400) return (seconds / 3600).toFixed(1) + "h";
    return (seconds / 86400).toFixed(1) + "d";
  }

  function renderActivity(series) {
    metricsActivity.replaceChildren();
    if (!series.length) return;
    var width = 720, height = 140, pad = 8;
    var peak = Math.max.apply(null, series.map(function (point) { return point.count; }).concat([1]));
    var slot = (width - 2 * pad) / series.length;
    var barWidth = Math.max(1, Math.min(slot - 2, 24));
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Tasks submitted over time");
    series.forEach(function (point, index) {
      var barHeight = Math.max(point.count ? 2 : 0, (point.count / peak) * (height - 2 * pad));
      var bar = document.createElementNS(svg.namespaceURI, "rect");
      bar.setAttribute("x", (pad + index * slot + (slot - barWidth) / 2).toFixed(1));
      bar.setAttribute("y", (height - pad - barHeight).toFixed(1));
      bar.setAttribute("width", barWidth.toFixed(1));
      bar.setAttribute("height", barHeight.toFixed(1));
      bar.setAttribute("rx", "2");
      bar.setAttribute("class", "metrics-bar");
      var label = document.createElementNS(svg.namespaceURI, "title");
      label.textContent = point.period + ": " + point.count;
      bar.appendChild(label);
      svg.appendChild(bar);
    });
    metricsActivity.appendChild(svg);
  }

  function renderDistribution(distribution) {
    metricsDistribution.replaceChildren();
    if (!distribution.length) {
      var empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No TaskType usage in this window.";
      metricsDistribution.appendChild(empty);
      return;
    }
    var total = distribution.reduce(function (sum, item) { return sum + item.tasks; }, 0) || 1;
    distribution.forEach(function (item) {
      var row = document.createElement("div"); row.className = "metrics-bar-row";
      var name = document.createElement("span"); name.className = "metrics-bar-name";
      name.textContent = item.label || item.task_type;
      var track = document.createElement("span"); track.className = "metrics-bar-track";
      var fill = document.createElement("span"); fill.className = "metrics-bar-fill";
      fill.style.width = ((item.tasks / total) * 100).toFixed(1) + "%";
      track.appendChild(fill);
      var value = document.createElement("span"); value.className = "metrics-bar-value";
      value.textContent = item.tasks + (item.gpu ? " · GPU" : "");
      row.append(name, track, value);
      metricsDistribution.appendChild(row);
    });
  }

  function renderMetrics(data) {
    metricsPeriod.textContent = data.period + " · " + data.window + " window";
    document.getElementById("metricsSubmitted").textContent = data.tasks_submitted;
    document.getElementById("metricsCompleted").textContent = data.tasks_completed;
    document.getElementById("metricsFailed").textContent = data.tasks_failed;
    document.getElementById("metricsSuccessRate").textContent =
      data.success_rate == null ? "—" : Math.round(data.success_rate * 100) + "%";
    document.getElementById("metricsGpuMinutes").textContent = data.gpu_minutes.toLocaleString(undefined, { maximumFractionDigits: 1 });
    document.getElementById("metricsMedianRuntime").textContent = formatRuntime(data.median_runtime_seconds);
    metricsComposition.textContent = data.cpu_tasks + " CPU · " + data.gpu_tasks + " GPU · " +
      formatRuntime(data.total_runtime_seconds) + " total runtime";
    metricsEmpty.hidden = data.tasks_submitted > 0;
    renderActivity(data.activity);
    renderDistribution(data.distribution);
  }

  function selectMetricsWindow(value) {
    metricsWindow.querySelectorAll("button[data-window]").forEach(function (button) {
      var selected = button.dataset.window === value;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    metricsPeriod.dataset.window = value;
  }

  // Only the newest request may paint: a slow earlier window must not land on
  // top of a later selection.
  var metricsGeneration = 0;

  function loadMetrics(value) {
    var generation = ++metricsGeneration;
    metricsPeriod.textContent = "Loading…";
    metricsPeriod.dataset.window = value;
    A.authFetch("/compute/api/user-metrics?window=" + encodeURIComponent(value))
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        if (generation !== metricsGeneration) return;
        selectMetricsWindow(data.window);
        renderMetrics(data);
      })
      .catch(function () {
        if (generation !== metricsGeneration) return;
        metricsPeriod.textContent = "Unable to load metrics.";
      });
  }

  metricsWindow.querySelectorAll("button[data-window]").forEach(function (button) {
    button.addEventListener("click", function () { loadMetrics(button.dataset.window); });
  });
  loadMetrics("30d");

  /* ---- User identity ---- */

  A.authFetch("/compute/api/auth/me")
    .then(function (r) { return r.json(); })
    .then(function (user) {
      var label = user.role === "guest" ? " (guest account)" : "";
      infoEl.textContent = "Logged in as " + user.username + " (" + user.email + ")" + label;
      document.getElementById("profileUsername").textContent = user.username;
      document.getElementById("profileEmail").textContent = user.email;
      document.getElementById("profileFullName").textContent = user.full_name || "Not provided";
      document.getElementById("profileAffiliation").textContent = user.affiliation || "Not provided";
      document.getElementById("profilePosition").textContent =
        POSITION_LABELS[user.position] || user.position || "Not provided";
      document.getElementById("profilePiName").textContent = user.pi_name || "Not provided";
      document.getElementById("profileRole").textContent = ROLE_LABELS[user.role] || user.role || "Not provided";
      if (user.role === "guest") {
        restrictGuestSections();
      }
    })
    .catch(function () {
      infoEl.textContent = "Unable to load profile.";
    });

  /* ---- Password change ---- */

  var form = document.getElementById("passwordForm");
  var statusEl = document.getElementById("status");
  var submitBtn = document.getElementById("submitBtn");

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    statusEl.className = "status-msg";
    statusEl.textContent = "";
    submitBtn.disabled = true;

    var newPassword = document.getElementById("newPassword").value;
    var confirmPassword = document.getElementById("confirmPassword").value;

    if (newPassword !== confirmPassword) {
      statusEl.className = "status-msg error";
      statusEl.textContent = "New passwords do not match.";
      submitBtn.disabled = false;
      return;
    }

    if (newPassword.length < 8) {
      statusEl.className = "status-msg error";
      statusEl.textContent = "Password must be at least 8 characters.";
      submitBtn.disabled = false;
      return;
    }

    var payload = {
      current_password: document.getElementById("currentPassword").value,
      new_password: newPassword
    };

    A.authFetch("/compute/api/auth/me", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        submitBtn.disabled = false;
        if (result.ok) {
          statusEl.className = "status-msg success";
          statusEl.textContent = "Password updated successfully.";
          form.reset();
        } else {
          statusEl.className = "status-msg error";
          statusEl.textContent = result.data.error || "Failed to update password.";
        }
      })
      .catch(function () {
        submitBtn.disabled = false;
        statusEl.className = "status-msg error";
        statusEl.textContent = "Network error. Please try again.";
      });
  });

  /* ---- API key management ---- */

  var apiKeyStatus = document.getElementById("apiKeyStatus");
  var generateBtn = document.getElementById("generateKeyBtn");
  var revokeBtn = document.getElementById("revokeKeyBtn");
  var apiKeyDisplay = document.getElementById("apiKeyDisplay");
  var apiKeyValue = document.getElementById("apiKeyValue");
  var apiKeyMsg = document.getElementById("apiKeyMsg");

  function refreshApiKeyStatus() {
    A.authFetch("/compute/api/auth/me/api-key")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.has_api_key) {
          apiKeyStatus.textContent = "You have an active API key. Use it with the X-API-Key header for programmatic access.";
          generateBtn.style.display = "inline-block";
          revokeBtn.style.display = "inline-block";
          generateBtn.textContent = "Regenerate API Key";
        } else {
          apiKeyStatus.textContent = "No API key configured. Generate one for programmatic access.";
          generateBtn.style.display = "inline-block";
          revokeBtn.style.display = "none";
          generateBtn.textContent = "Generate API Key";
        }
        /* ponytail: only hide the key display if the user is NOT currently
           looking at a freshly-generated key (the value input is empty). */
        if (!apiKeyValue.value) {
          apiKeyDisplay.style.display = "none";
        }
      })
      .catch(function () {
        apiKeyStatus.textContent = "Unable to load API key status.";
      });
  }

  generateBtn.addEventListener("click", function () {
    apiKeyMsg.className = "status-msg";
    apiKeyMsg.textContent = "";
    generateBtn.disabled = true;

    A.authFetch("/compute/api/auth/me/api-key", { method: "POST" })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        generateBtn.disabled = false;
        if (result.ok && result.data.api_key) {
          apiKeyValue.value = result.data.api_key;
          apiKeyDisplay.style.display = "block";
          apiKeyMsg.className = "status-msg success";
          apiKeyMsg.textContent = result.data.message;
          refreshApiKeyStatus();
          generateBtn.textContent = "Regenerate API Key";
          revokeBtn.style.display = "inline-block";
          apiKeyStatus.textContent = "You have an active API key.";
        } else {
          apiKeyMsg.className = "status-msg error";
          apiKeyMsg.textContent = result.data.error || "Failed to generate API key.";
        }
      })
      .catch(function () {
        generateBtn.disabled = false;
        apiKeyMsg.className = "status-msg error";
        apiKeyMsg.textContent = "Network error. Please try again.";
      });
  });

  revokeBtn.addEventListener("click", async function () {
    if (!await UI.confirm({ title: "Revoke API key?", message: "All existing uses of this key will stop working.", confirmLabel: "Revoke API key" })) return;
    apiKeyMsg.className = "status-msg";
    apiKeyMsg.textContent = "";
    revokeBtn.disabled = true;

    A.authFetch("/compute/api/auth/me/api-key", { method: "DELETE" })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        revokeBtn.disabled = false;
        if (result.ok) {
          apiKeyMsg.className = "status-msg success";
          apiKeyMsg.textContent = "API key revoked.";
          apiKeyDisplay.style.display = "none";
          refreshApiKeyStatus();
        } else {
          apiKeyMsg.className = "status-msg error";
          apiKeyMsg.textContent = result.data.error || "Failed to revoke API key.";
        }
      })
      .catch(function () {
        revokeBtn.disabled = false;
        apiKeyMsg.className = "status-msg error";
        apiKeyMsg.textContent = "Network error. Please try again.";
      });
  });

  refreshApiKeyStatus();

  /* ---- Logout ---- */
  document.getElementById("logoutBtn").addEventListener("click", A.logout);

  /* ---- Copy API key ---- */
  var copyBtn = document.getElementById("copyKeyBtn");
  copyBtn.addEventListener("click", function () {
    var input = document.getElementById("apiKeyValue");
    input.select();
    input.setSelectionRange(0, 99999); /* mobile */
    try {
      navigator.clipboard.writeText(input.value).then(function () {
        copyBtn.textContent = "✓";
        setTimeout(function () { copyBtn.textContent = "⨏"; }, 1600);
      });
    } catch (_) {
      /* fallback: selection above already copied for manual Ctrl+C */
      copyBtn.textContent = "✓";
      setTimeout(function () { copyBtn.textContent = "⨏"; }, 1600);
    }
  });
})();
