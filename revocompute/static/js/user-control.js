/* REvoCompute — User Control page */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  "use strict";
  var A = window.REvoDesignAuth;
  var T = window.REvoDesignTheme;
  var UI = window.REvoComputeUI;

  T.initToggle(document.getElementById("themeToggle"));

  // ---- Status label maps ----

  var REG_LABELS = {
    email_sent: "Email Sent",
    verified: "Verified",
    approved: "Approved",
    rejected: "Rejected",
  };
  var USER_LABELS = {
    pending: "Pending",
    active: "Active",
    banned: "Banned",
  };
  var ROLE_LABELS = {
    admin: "Admin",
    user: "User",
    guest: "Guest",
  };
  var POSITION_LABELS = {
    undergraduate_student: "Undergraduate student",
    masters_student: "Master’s student",
    phd_student: "PhD student",
    postdoctoral_researcher: "Postdoctoral researcher",
    research_assistant: "Research assistant",
    lecturer: "Lecturer",
    assistant_professor: "Assistant professor",
    associate_professor: "Associate professor",
    professor: "Professor",
    industry_researcher: "Industry researcher",
    other: "Other",
  };

  // ---- Tab switching ----

  var tabs = document.querySelectorAll(".sub-tab");
  var panels = {
    audit: document.getElementById("tab-audit"),
    access: document.getElementById("tab-access"),
    add: document.getElementById("tab-add"),
  };

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      Object.keys(panels).forEach(function (k) {
        panels[k].style.display = k === tab.dataset.tab ? "block" : "none";
      });
      if (tab.dataset.tab === "audit") loadUsers();
      if (tab.dataset.tab === "access") loadAccessRequests();
    });
  });

  // ---- Batch bar ----

  var batchBar = document.getElementById("batchBar");
  var batchCount = document.getElementById("batchCount");
  var selectAll = document.getElementById("selectAll");
  var currentUsername = null;

  selectAll.addEventListener("change", function () {
    var checks = document.querySelectorAll(".user-select:not(:disabled)");
    checks.forEach(function (cb) { cb.checked = selectAll.checked; });
    updateBatchBar();
  });

  function updateBatchBar() {
    var checks = document.querySelectorAll(".user-select:checked");
    var count = checks.length;
    batchBar.style.display = count > 0 ? "" : "none";
    batchCount.textContent = count + " selected";
  }

  document.getElementById("batchBar").addEventListener("click", async function (e) {
    var btn = e.target.closest(".batch-action");
    if (!btn) return;
    var action = btn.dataset.action;
    var checks = document.querySelectorAll(".user-select:checked");
    var ids = [];
    checks.forEach(function (cb) { ids.push(cb.dataset.uid); });
    if (!ids.length) return;

    var labels = { enable: "Enable", disable: "Disable", delete: "Delete" };
    if (!await UI.confirm({ title: labels[action] + " selected users?", message: ids.length + " selected user(s) will be affected.", confirmLabel: labels[action] + " " + ids.length + " users", destructive: action !== "enable" })) return;
    btn.disabled = true;

    A.authFetch("/compute/api/auth/admin/users/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action, user_ids: ids }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (result) {
        if (result.ok) {
          selectAll.checked = false;
          loadUsers();
        } else {
          UI.alert(result.data.error || "Batch action failed.");
          btn.disabled = false;
        }
      })
      .catch(function () { UI.alert("Network error."); btn.disabled = false; });
  });

  // ---- Load user list (Tab A) ----

  var userTableBody = document.getElementById("userTableBody");
  var COLSPAN = 7;
  var users = [];
  var userSearch = document.getElementById("userSearch");
  var userRoleFilter = document.getElementById("userRoleFilter");
  var userStatusFilter = document.getElementById("userStatusFilter");
  var userCount = document.getElementById("userCount");

  function loadCurrentUser() {
    return A.authFetch("/compute/api/auth/me")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        currentUsername = data.username || null;
      });
  }

  function loadUsers() {
    userTableBody.innerHTML = '<tr><td colspan="' + COLSPAN + '" class="empty">Loading&hellip;</td></tr>';
    selectAll.checked = false;
    batchBar.style.display = "none";
    A.authFetch("/compute/api/auth/admin/users")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        users = data.users || [];
        renderUsers();
      })
      .catch(function () {
        userTableBody.innerHTML = '<tr><td colspan="' + COLSPAN + '" class="empty error">Failed to load users.</td></tr>';
      });
  }

  function renderUsers() {
    var query = userSearch.value.trim().toLowerCase();
    var visible = users.filter(function (u) {
      return (userRoleFilter.value === "all" || u.role === userRoleFilter.value) &&
        (userStatusFilter.value === "all" || u.user_status === userStatusFilter.value) &&
        (!query || [u.full_name, u.username, u.email, u.affiliation].filter(Boolean).join(" ").toLowerCase().includes(query));
    });
    userTableBody.replaceChildren();
    userCount.textContent = visible.length + " of " + users.length + " users";
    if (!visible.length) {
      userTableBody.innerHTML = '<tr><td colspan="' + COLSPAN + '" class="empty">No users match these filters.</td></tr>';
      return;
    }
    visible.forEach(renderUserRow);
  }

  function isCurrentUser(u) {
    return currentUsername && u.username === currentUsername;
  }

  function userIdentity(u) {
    return (u && (u.full_name || u.username || u.email || u.id)) ? String(u.full_name || u.username || u.email || u.id) : "Unknown user";
  }

  function renderUserRow(u) {
    var tr = document.createElement("tr");
    var regLabel = REG_LABELS[u.registration_status] || u.registration_status || "—";
    var userLabel = USER_LABELS[u.user_status] || u.user_status || "—";
    var actionsHtml = buildActionButtons(u);
    var self = isCurrentUser(u);
    var selectAttrs = ' class="user-select" data-uid="' + u.id + '"';
    if (self) selectAttrs += ' disabled title="You cannot batch-disable or delete your own account"';

    var gpuLabel = u.allow_gpu_use ? '<span class="gpu-badge on">GPU</span>' : '<span class="gpu-badge off">—</span>';

    tr.innerHTML =
      '<td class="col-select"><input type="checkbox"' + selectAttrs + '></td>' +
      '<td class="col-identity" data-label="User"><strong>' + escapeHtml(userIdentity(u)) + '</strong><span>' + escapeHtml(u.username || u.email || "—") + '</span></td>' +
      '<td class="col-affil" data-label="Affiliation">' + escapeHtml(u.affiliation || "—") + '</td>' +
      '<td class="col-role" data-label="Role"><span class="status-badge ' + escapeAttr(u.role || "user") + '">' + escapeHtml(ROLE_LABELS[u.role] || u.role || "User") + '</span></td>' +
      '<td class="col-gpu" data-label="GPU">' + gpuLabel + '</td>' +
      '<td class="col-status" data-label="Status"><span class="status-badge ' + escapeAttr(u.registration_status) + '">' + escapeHtml(regLabel) + '</span> <span class="status-badge ' + escapeAttr(u.user_status) + '">' + escapeHtml(userLabel) + '</span></td>' +
      '<td class="col-actions" data-label="Actions">' + actionsHtml + '</td>';
    // Store full user data for inline edit
    tr._userData = u;
    userTableBody.appendChild(tr);

    // ponytail: attach listener per-row so checkbox updates batch bar
    var cb = tr.querySelector(".user-select");
    if (cb) cb.addEventListener("change", updateBatchBar);
  }

  function buildActionButtons(u) {
    var buttons = "";
    var reg = u.registration_status;
    var us = u.user_status;
    var self = isCurrentUser(u);
    // Approve / Reject during registration flow
    if (reg === "email_sent" || reg === "verified") {
      buttons += '<button class="user-action-btn approve" data-id="' + u.id + '" data-action="approve">Approve</button>';
      buttons += '<button class="user-action-btn reject" data-id="' + u.id + '" data-action="reject">Reject</button>';
    }
    // Ban active users
    if (us === "active" && !self) {
      buttons += '<button class="user-action-btn ban" data-id="' + u.id + '" data-action="ban">Ban</button>';
    }
    // Re-enable banned or rejected users
    if (us === "banned" || reg === "rejected") {
      buttons += '<button class="user-action-btn enable" data-id="' + u.id + '" data-action="enable">Enable</button>';
    }
    buttons += '<button class="user-action-btn detail" data-id="' + u.id + '" data-action="detail">Details</button>';
    buttons += '<button class="user-action-btn modify" data-id="' + u.id + '" data-action="modify">Modify</button>';
    buttons += '<button class="user-action-btn access" data-id="' + u.id + '" data-action="access">Runner access</button>';
    return buttons;
  }

  // ---- Action button handler (delegated) ----

  userTableBody.addEventListener("click", async function (e) {
    var btn = e.target.closest(".user-action-btn");
    if (!btn) return;
    var userId = btn.dataset.id;
    var action = btn.dataset.action;
    if (!action) return;
    var targetUser = btn.closest("tr")._userData;

    if (action === "access") {
      document.querySelector('.sub-tab[data-tab="access"]').click();
      loadUserAccess(userId, btn.closest("tr")._userData);
      return;
    }

    if (action === "detail") {
      showUserDetails(targetUser);
      return;
    }

    if (action === "modify") {
      showEditUser(targetUser);
      return;
    }

    var payload = {};
    if (action === "approve") {
      payload = { registration_status: "approved", user_status: "active" };
    } else if (action === "reject") {
      payload = { registration_status: "rejected" };
    } else if (action === "ban") {
      payload = { user_status: "banned" };
    } else if (action === "enable") {
      payload = { user_status: "active", registration_status: "approved" };
    }

    var labels = { approve: "Approve", reject: "Reject", ban: "Ban", enable: "Enable" };
    if (!await UI.confirm({ title: labels[action] + " " + userIdentity(targetUser) + "?", message: "This changes the account's registration or access state.", confirmLabel: labels[action] + " user", destructive: action !== "approve" && action !== "enable" })) return;

    btn.disabled = true;
    A.authFetch("/compute/api/auth/admin/users/" + userId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (result) {
        if (result.ok) { loadUsers(); }
        else { UI.alert(result.data.error || "Action failed."); btn.disabled = false; }
      })
      .catch(function () { UI.alert("Network error."); btn.disabled = false; });
  });

  function showUserDetails(u) {
    var details = document.createElement("dl"); details.className = "metadata-rows user-detail";
    [
      ["Email", u.email], ["Affiliation", u.affiliation], ["Position", POSITION_LABELS[u.position] || u.position],
      ["PI / supervisor", u.pi_name], ["Registration IP", u.registration_ip], ["Country", u.registration_country],
      ["Registration", REG_LABELS[u.registration_status] || u.registration_status],
      ["Account", USER_LABELS[u.user_status] || u.user_status],
    ].forEach(function (item) {
      var row = document.createElement("div"); var term = document.createElement("dt"); var value = document.createElement("dd");
      term.textContent = item[0]; value.textContent = item[1] || "Not provided"; row.append(term, value); details.appendChild(row);
    });
    UI.openDialog({ title: userIdentity(u), content: details, cancelLabel: "Close" });
  }

  async function showEditUser(u) {
    var self = isCurrentUser(u);
    var form = document.createElement("div"); form.className = "user-edit-grid";
    form.innerHTML =
      '<label class="field">Email<input type="email" class="text-input" data-field="email" value="' + escapeHtml(u.email || "") + '"></label>' +
      '<label class="field">Full name<input class="text-input" data-field="full_name" value="' + escapeHtml(u.full_name || "") + '" maxlength="128"></label>' +
      '<label class="field">Affiliation<input class="text-input" data-field="affiliation" value="' + escapeHtml(u.affiliation || "") + '"></label>' +
      '<label class="field">Position<select class="text-input" data-field="position">' + buildPositionOptions(u.position) + '</select></label>' +
      '<label class="field">PI / supervisor<input class="text-input" data-field="pi_name" value="' + escapeHtml(u.pi_name || "") + '" maxlength="128"></label>' +
      '<label class="field">Role<select class="text-input" data-field="role"' + (self ? " disabled" : "") + '>' +
        '<option value="admin"' + (u.role === "admin" ? " selected" : "") + '>Admin</option><option value="user"' + (u.role === "user" ? " selected" : "") + '>User</option><option value="guest"' + (u.role === "guest" ? " selected" : "") + '>Guest</option></select></label>' +
      '<label class="field">Registration<select class="text-input" data-field="registration_status"><option value="approved"' + (u.registration_status === "approved" ? " selected" : "") + '>Approved</option><option value="rejected"' + (u.registration_status === "rejected" ? " selected" : "") + '>Rejected</option></select></label>' +
      '<label class="field">Account<select class="text-input" data-field="user_status"><option value="active"' + (u.user_status === "active" ? " selected" : "") + '>Active</option><option value="banned"' + (u.user_status === "banned" ? " selected" : "") + (self ? " disabled" : "") + '>Banned</option></select></label>' +
      '<label class="field check-field"><input type="checkbox" data-field="allow_gpu_use"' + (u.allow_gpu_use ? " checked" : "") + '> Admit GPU tasks</label>' +
      '<label class="field">New password <span class="muted">(optional)</span><input type="password" class="text-input" data-field="password" minlength="8" autocomplete="new-password"></label>';
    var submitted = await UI.openDialog({ title: "Modify " + userIdentity(u), content: form, confirmLabel: "Save user", cancelLabel: "Cancel", destructive: false, value: function () {
      var payload = {};
      form.querySelectorAll("[data-field]").forEach(function (input) { payload[input.dataset.field] = input.type === "checkbox" ? input.checked : input.value.trim(); });
      if (!payload.password) delete payload.password;
      if (!payload.position) payload.position = null;
      if (self) delete payload.role;
      return payload;
    } });
    if (!submitted) return;
    if (self && submitted.user_status === "banned") { await UI.alert("You cannot ban your own account."); return; }
    A.authFetch("/compute/api/auth/admin/users/" + u.id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(submitted) })
      .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error || "Update failed."); }); })
      .then(loadUsers).catch(function (error) { UI.alert(error.message || "Network error."); });
  }

  // ---- Runner access ----

  var accessQueue = document.getElementById("accessRequestQueue");
  var accessPolicyOverview = document.getElementById("accessPolicyOverview");
  var accessPolicyDetail = document.getElementById("accessPolicyDetail");
  var accessActivity = document.getElementById("accessActivity");
  var accessPanel = document.getElementById("userAccessPanel");
  var accessPoliciesByEntitlement = new Map();

  function loadAccessRequests() {
    loadAccessPolicyOverview();
    loadAccessActivity();
    accessQueue.innerHTML = '<p class="empty">Loading&hellip;</p>';
    A.authFetch("/compute/api/auth/admin/access/requests")
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        accessQueue.replaceChildren();
        if (!data.requests.length) { accessQueue.innerHTML = '<p class="empty">No pending access requests.</p>'; return; }
        data.requests.forEach(function (item) {
          var row = document.createElement("article"); row.className = "access-row";
          var copy = document.createElement("div");
          var title = document.createElement("strong"); title.textContent = item.full_name || item.username;
          var entitlement = document.createElement("span"); entitlement.textContent = item.entitlement;
          var reason = document.createElement("p"); reason.textContent = "Reason: " + item.reason;
          copy.append(title, entitlement, reason);
          var actions = document.createElement("div"); actions.className = "actions";
          var approve = document.createElement("button"); approve.className = "btn btn-primary"; approve.textContent = "Approve";
          approve.addEventListener("click", function () { openAccessDialog({ requestId: item.id, request: item }); });
          var reject = document.createElement("button"); reject.className = "btn btn-soft"; reject.textContent = "Reject";
          reject.addEventListener("click", function () { rejectAccessRequest(item.id); });
          actions.append(approve, reject); row.append(copy, actions); accessQueue.appendChild(row);
        });
      })
      .catch(function () { accessQueue.innerHTML = '<p class="empty error">Failed to load access requests.</p>'; });
  }

  function loadAccessPolicyOverview() {
    accessPolicyOverview.innerHTML = '<p class="empty">Loading&hellip;</p>';
    A.authFetch("/compute/api/auth/admin/access/policies")
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        accessPolicyOverview.replaceChildren();
        var policies = data.policies || [];
        accessPoliciesByEntitlement.clear();
        policies.forEach(function (policy) {
          (policy.requires || []).forEach(function (entitlement) { accessPoliciesByEntitlement.set(entitlement, policy); });
        });
        if (!policies.length) { accessPolicyOverview.innerHTML = '<p class="empty">No restricted Runner policies are configured.</p>'; return; }
        policies.forEach(function (policy) {
          var row = document.createElement("article"); row.className = "access-row policy-summary";
          var title = document.createElement("strong"); title.textContent = policy.label || policy.policy_id;
          row.appendChild(title);
          [["Authorized", policy.authorized_users], ["Pending", policy.pending_requests], ["Suspended", policy.suspended_users]].forEach(function (item) {
            var count = document.createElement("span"); count.className = "policy-count";
            var value = document.createElement("b"); value.textContent = String(item[1] == null ? 0 : item[1]);
            count.append(value, document.createTextNode(item[0])); row.appendChild(count);
          });
          var manage = document.createElement("button"); manage.className = "btn btn-soft"; manage.textContent = "Manage";
          manage.addEventListener("click", function () { loadPolicyDetail(policy.policy_id); }); row.appendChild(manage);
          accessPolicyOverview.appendChild(row);
        });
      })
      .catch(function () { accessPolicyOverview.innerHTML = '<p class="empty error">Failed to load policy overview.</p>'; });
  }

  function loadPolicyDetail(policyId) {
    accessPolicyDetail.hidden = false; accessPolicyDetail.innerHTML = '<p class="empty">Loading&hellip;</p>';
    A.authFetch("/compute/api/auth/admin/access/policies/" + encodeURIComponent(policyId))
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        accessPolicyDetail.replaceChildren();
        var heading = document.createElement("h3"); heading.textContent = data.policy.label; accessPolicyDetail.appendChild(heading);
        [["Authorized users", data.authorized_users], ["Pending requests", data.pending_requests], ["Suspended users", data.suspended_users]].forEach(function (group) {
          var label = document.createElement("strong"); label.textContent = group[0]; accessPolicyDetail.appendChild(label);
          if (!group[1].length) { var empty = document.createElement("p"); empty.className = "empty"; empty.textContent = "None"; accessPolicyDetail.appendChild(empty); return; }
          group[1].forEach(function (item) {
            var row = document.createElement("article"); row.className = "access-row";
            var name = document.createElement("span"); name.textContent = item.full_name || item.username; row.appendChild(name);
            if (item.retry_after_seconds) {
              var clear = document.createElement("button"); clear.className = "btn btn-soft"; clear.textContent = "Clear suspension";
              clear.addEventListener("click", function () { clearPolicySuspension(item.user_id, policyId); }); row.appendChild(clear);
            }
            accessPolicyDetail.appendChild(row);
          });
        });
      })
      .catch(function () { accessPolicyDetail.innerHTML = '<p class="empty error">Failed to load policy details.</p>'; });
  }

  function clearPolicySuspension(userId, policyId) {
    A.authFetch("/compute/api/auth/admin/users/" + userId + "/access/" + encodeURIComponent(policyId) + "/clear-suspension", { method: "POST" })
      .then(function (r) { if (!r.ok) throw new Error(); loadPolicyDetail(policyId); loadAccessPolicyOverview(); loadAccessActivity(); })
      .catch(function () { UI.alert("Failed to clear suspension."); });
  }

  function loadAccessActivity() {
    accessActivity.innerHTML = '<p class="empty">Loading&hellip;</p>';
    A.authFetch("/compute/api/auth/admin/access/events?limit=20")
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        accessActivity.replaceChildren();
        var events = data.events || [];
        if (!events.length) { accessActivity.innerHTML = '<p class="empty">No recent restricted Runner activity.</p>'; return; }
        events.forEach(function (event) {
          var row = document.createElement("article"); row.className = "access-row";
          var copy = document.createElement("div");
          var title = document.createElement("strong"); title.textContent = event.username || event.user_name || "Unknown user";
          var detail = document.createElement("span"); detail.textContent = " " + (event.label || event.policy_id || "Restricted Runner") + " — " + (event.outcome || event.decision || "RECORDED");
          copy.append(title, detail); row.appendChild(copy); accessActivity.appendChild(row);
        });
      })
      .catch(function () { accessActivity.innerHTML = '<p class="empty error">Unable to load recent activity.</p>'; });
  }

  function loadUserAccess(userId, user) {
    accessPanel.hidden = false;
    document.getElementById("userAccessTitle").textContent = "Runner access — " + (user.full_name || user.username);
    var policiesRoot = document.getElementById("userAccessPolicies");
    var historyRoot = document.getElementById("userAccessHistory");
    policiesRoot.innerHTML = '<p class="empty">Loading&hellip;</p>'; historyRoot.replaceChildren();
    A.authFetch("/compute/api/auth/admin/users/" + userId + "/entitlements")
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        policiesRoot.replaceChildren(); historyRoot.replaceChildren();
        data.policies.forEach(function (policy) {
          var row = document.createElement("article"); row.className = "access-row";
          var copy = document.createElement("div");
          var title = document.createElement("strong"); title.textContent = policy.label;
          var state = document.createElement("span"); state.textContent = policy.granted ? "Granted" : (policy.request_status === "pending" ? "Pending" : "Not granted");
          if (policy.suspended) state.textContent += " · Suspended (" + policy.retry_after_seconds + "s remaining)";
          copy.append(title, state); row.appendChild(copy);
          if (!policy.granted) {
            var grant = document.createElement("button"); grant.className = "btn btn-soft"; grant.textContent = "Grant";
            grant.addEventListener("click", function () { openAccessDialog({ userId: userId, entitlement: policy.missing_entitlements[0], user: user }); });
            row.appendChild(grant);
          }
          if (policy.suspended) {
            var clear = document.createElement("button"); clear.className = "btn btn-soft"; clear.textContent = "Clear suspension";
            clear.addEventListener("click", function () {
              A.authFetch("/compute/api/auth/admin/users/" + userId + "/access/" + encodeURIComponent(policy.policy_id) + "/clear-suspension", { method: "POST" })
                .then(function (r) { if (!r.ok) throw new Error(); loadUserAccess(userId, user); loadAccessPolicyOverview(); loadAccessActivity(); })
                .catch(function () { UI.alert("Failed to clear suspension."); });
            });
            row.appendChild(clear);
          }
          policiesRoot.appendChild(row);
        });
        data.grants.forEach(function (grant) {
          var row = document.createElement("article"); row.className = "access-row";
          var copy = document.createElement("div");
          var title = document.createElement("strong"); title.textContent = grant.entitlement;
          var state = document.createElement("span");
          state.textContent = grant.revoked_at ? "Revoked" : (grant.expires_at && grant.expires_at * 1000 <= Date.now() ? "Expired" : "Active");
          copy.append(title, state); row.appendChild(copy);
          if (!grant.revoked_at && (!grant.expires_at || grant.expires_at * 1000 > Date.now())) {
            var revoke = document.createElement("button"); revoke.className = "btn btn-soft"; revoke.textContent = "Revoke";
            revoke.addEventListener("click", function () { revokeGrant(userId, grant.id, user); }); row.appendChild(revoke);
          }
          historyRoot.appendChild(row);
        });
        if (!data.policies.length) policiesRoot.innerHTML = '<p class="empty">No restricted Runner policies are configured.</p>';
        if (!data.grants.length) historyRoot.innerHTML = '<p class="empty">No grant history.</p>';
      })
      .catch(function () { policiesRoot.innerHTML = '<p class="empty error">Failed to load Runner access.</p>'; });
  }

  async function openAccessDialog(target) {
    var fields = document.createElement("div"); fields.className = "access-decision-fields";
    var entitlement = target.request ? target.request.entitlement : target.entitlement;
    var policy = accessPoliciesByEntitlement.get(entitlement);
    var grants = [];
    var targetUserId = target.request ? target.request.user_id : target.userId;
    if (targetUserId) {
      try {
        var historyResponse = await A.authFetch("/compute/api/auth/admin/users/" + targetUserId + "/entitlements");
        if (historyResponse.ok) grants = (await historyResponse.json()).grants || [];
      } catch (_) { /* decision remains available when history cannot be loaded */ }
    }
    var evidence = target.request ? '<div class="access-evidence"><strong>' + escapeHtml(userIdentity(target.request)) + '</strong>' +
      '<span>' + escapeHtml(target.request.email || "Email unavailable") + ' · ' + escapeHtml(REG_LABELS[target.request.registration_status] || target.request.registration_status || "Verification unknown") + '</span>' +
      '<span>' + escapeHtml(target.request.affiliation || "Affiliation not provided") + ' · ' + escapeHtml(POSITION_LABELS[target.request.position] || target.request.position || "Position not provided") + '</span>' +
      '<span>PI / supervisor: ' + escapeHtml(target.request.pi_name || "Not provided") + '</span><span>Policy entitlement: ' + escapeHtml(target.request.entitlement) + '</span>' +
      '<p>Request note: ' + escapeHtml(target.request.reason || "No request note provided.") + '</p></div>' : "";
    var policyContext = policy ? '<div class="access-evidence"><strong>' + escapeHtml(policy.label) + '</strong><p>' +
      escapeHtml(policy.description) + '</p>' + (policy.notice && policy.notice.summary ? '<p>' + escapeHtml(policy.notice.summary) + '</p>' : '') +
      (policy.license && policy.license.url ? '<a href="' + escapeHtml(policy.license.url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(policy.license.name || "Upstream licence") + '</a>' : '') + '</div>' : "";
    var relevantGrants = grants.filter(function (grant) { return grant.entitlement === entitlement; });
    var grantHistory = '<div class="access-evidence"><strong>Previous entitlement history</strong>' +
      (relevantGrants.length ? relevantGrants.map(function (grant) {
        var state = grant.revoked_at ? "Revoked" : (grant.expires_at && grant.expires_at * 1000 <= Date.now() ? "Expired" : "Active");
        var expiry = grant.expires_at ? " · expires " + new Date(grant.expires_at * 1000).toLocaleString() : "";
        var basis = grant.basis ? String(grant.basis).replaceAll("_", " ") : "basis not recorded";
        return '<span>' + escapeHtml(state + " · " + basis + expiry) + '</span>';
      }).join("") : '<span>No previous grants for this entitlement.</span>') + '</div>';
    fields.innerHTML = evidence + policyContext + grantHistory +
      '<p class="muted">Confirm eligibility under the configured policy. This entitlement does not modify the upstream licence.</p>' +
      '<label class="field">Verification basis<select data-access="basis" class="text-input"><option value="lab_member">Lab member</option><option value="institutional_collaborator">Institutional collaborator</option><option value="individually_verified">Individually verified</option><option value="other">Other</option></select></label>' +
      '<label class="field">Expiry <span class="muted">(optional)</span><input data-access="expiry" type="datetime-local" class="text-input"></label>' +
      '<label class="field">Decision note <span class="muted">(optional)</span><textarea data-access="note" class="text-input" maxlength="1000" rows="3"></textarea></label>';
    var payload = await UI.openDialog({ title: target.requestId ? "Approve access request" : "Grant Runner access", content: fields, confirmLabel: "Confirm eligibility", cancelLabel: "Cancel", value: function () {
      var expiry = fields.querySelector('[data-access="expiry"]').value;
      return { basis: fields.querySelector('[data-access="basis"]').value, expires_at: expiry ? new Date(expiry).getTime() / 1000 : null, note: fields.querySelector('[data-access="note"]').value.trim() || null };
    } });
    if (!payload) return;
    var url;
    if (target.requestId) { url = "/compute/api/auth/admin/access/requests/" + target.requestId + "/decision"; payload.decision = "approved"; }
    else { url = "/compute/api/auth/admin/users/" + target.userId + "/entitlements"; payload.entitlement = target.entitlement; }
    A.authFetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error); }); })
      .then(function () { loadAccessRequests(); if (target.userId) loadUserAccess(target.userId, target.user); })
      .catch(function (error) { UI.alert(error.message || "Access update failed."); });
  }

  async function rejectAccessRequest(requestId) {
    var note = await UI.prompt({ title: "Reject access request?", label: "Decision note (optional)", confirmLabel: "Reject request", destructive: true }); if (note === null) return;
    A.authFetch("/compute/api/auth/admin/access/requests/" + requestId + "/decision", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "rejected", note: note || null }),
    }).then(function (r) { if (!r.ok) throw new Error(); loadAccessRequests(); }).catch(function () { UI.alert("Rejection failed."); });
  }

  async function revokeGrant(userId, grantId, user) {
    if (!await UI.confirm({ title: "Revoke Runner entitlement?", message: "Future submissions by " + userIdentity(user) + " will no longer be authorized by this grant.", confirmLabel: "Revoke entitlement" })) return;
    A.authFetch("/compute/api/auth/admin/users/" + userId + "/entitlements/" + grantId + "/revoke", { method: "POST" })
      .then(function (r) { if (!r.ok) throw new Error(); loadUserAccess(userId, user); })
      .catch(function () { UI.alert("Revocation failed."); });
  }

  // ---- Add user form (Tab B) ----

  var addForm = document.getElementById("addUserForm");
  var addStatus = document.getElementById("addUserStatus");
  var TAB_AUDIT = document.querySelector('.sub-tab[data-tab="audit"]');

  addForm.addEventListener("submit", function (e) {
    e.preventDefault();
    addStatus.className = "status-msg";
    addStatus.textContent = "";

    var payload = {
      username: document.getElementById("newUsername").value.trim(),
      email: document.getElementById("newEmail").value.trim(),
      password: document.getElementById("newPassword").value,
      full_name: document.getElementById("newFullName").value.trim() || null,
      affiliation: document.getElementById("newAffiliation").value.trim(),
      position: document.getElementById("newPosition").value || null,
      pi_name: document.getElementById("newPiName").value.trim() || null,
      role: document.getElementById("newRole").value,
    };

    A.authFetch("/compute/api/auth/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (result) {
        if (result.ok) {
          addStatus.className = "status-msg ok";
          addStatus.textContent = "User created — " + result.data.username;
          addForm.reset();
          // Switch to audit tab so admin sees the new user
          if (TAB_AUDIT) TAB_AUDIT.click();
        } else {
          addStatus.className = "status-msg error";
          addStatus.textContent = result.data.error || "Failed to create user.";
        }
      })
      .catch(function () {
        addStatus.className = "status-msg error";
        addStatus.textContent = "Network error.";
      });
  });

  // ---- Logout ----

  document.getElementById("logoutBtn").addEventListener("click", A.logout);

  // ---- Helpers ----

  function escapeAttr(input) {
    if (!input) return "";
    return String(input).replace(/[^a-zA-Z0-9_-]/g, "");
  }

  function buildPositionOptions(selected) {
    var html = '<option value="">Not specified</option>';
    Object.keys(POSITION_LABELS).forEach(function (value) {
      html += '<option value="' + value + '"' + (selected === value ? " selected" : "") + '>' +
        escapeHtml(POSITION_LABELS[value]) + '</option>';
    });
    return html;
  }

  [userSearch, userRoleFilter, userStatusFilter].forEach(function (control) {
    control.addEventListener(control.tagName === "INPUT" ? "input" : "change", renderUsers);
  });

  // Initial load
  loadCurrentUser()
    .catch(function () { currentUsername = null; })
    .then(loadUsers);
})();
