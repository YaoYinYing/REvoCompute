/* REvoCompute — User Control page */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  "use strict";
  var A = window.REvoDesignAuth;
  var T = window.REvoDesignTheme;

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

  document.getElementById("batchBar").addEventListener("click", function (e) {
    var btn = e.target.closest(".batch-action");
    if (!btn) return;
    var action = btn.dataset.action;
    var checks = document.querySelectorAll(".user-select:checked");
    var ids = [];
    checks.forEach(function (cb) { ids.push(cb.dataset.uid); });
    if (!ids.length) return;

    var labels = { enable: "Enable", disable: "Disable", delete: "Delete" };
    if (!window.confirm(labels[action] + " " + ids.length + " user(s)?")) return;
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
          alert(result.data.error || "Batch action failed.");
          btn.disabled = false;
        }
      })
      .catch(function () { alert("Network error."); btn.disabled = false; });
  });

  // ---- Load user list (Tab A) ----

  var userTableBody = document.getElementById("userTableBody");
  var COLSPAN = 12;

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
        userTableBody.innerHTML = "";
        if (!data.users || !data.users.length) {
          userTableBody.innerHTML = '<tr><td colspan="' + COLSPAN + '" class="empty">No users found.</td></tr>';
          return;
        }
        data.users.forEach(function (u) { renderUserRow(u); });
      })
      .catch(function () {
        userTableBody.innerHTML = '<tr><td colspan="' + COLSPAN + '" class="empty error">Failed to load users.</td></tr>';
      });
  }

  function isCurrentUser(u) {
    return currentUsername && u.username === currentUsername;
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
      '<td class="col-email">' + escapeHtml(u.email || "—") + '</td>' +
      '<td class="col-ip muted">' + escapeHtml(u.registration_ip || "—") + (u.registration_country ? ' <span class="country-tag">' + escapeHtml(u.registration_country) + '</span>' : '') + '</td>' +
      '<td class="col-name">' + escapeHtml(u.full_name || "—") + '</td>' +
      '<td class="col-affil">' + escapeHtml(u.affiliation || "—") + '</td>' +
      '<td class="col-position">' + escapeHtml(POSITION_LABELS[u.position] || u.position || "—") + '</td>' +
      '<td class="col-pi">' + escapeHtml(u.pi_name || "—") + '</td>' +
      '<td class="col-role"><span class="status-badge ' + escapeAttr(u.role || "user") + '">' + escapeHtml(ROLE_LABELS[u.role] || u.role || "User") + '</span></td>' +
      '<td class="col-gpu">' + gpuLabel + '</td>' +
      '<td class="col-reg"><span class="status-badge ' + escapeAttr(u.registration_status) + '">' + escapeHtml(regLabel) + '</span></td>' +
      '<td class="col-user"><span class="status-badge ' + escapeAttr(u.user_status) + '">' + escapeHtml(userLabel) + '</span></td>' +
      '<td class="col-actions">' + actionsHtml + '</td>';
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
    // Always show Modify
    buttons += '<button class="user-action-btn modify" data-id="' + u.id + '" data-action="modify">Modify</button>';
    buttons += '<button class="user-action-btn access" data-id="' + u.id + '" data-action="access">Runner access</button>';
    return buttons;
  }

  // ---- Action button handler (delegated) ----

  userTableBody.addEventListener("click", function (e) {
    var btn = e.target.closest(".user-action-btn");
    if (!btn) return;
    var userId = btn.dataset.id;
    var action = btn.dataset.action;

    if (action === "access") {
      document.querySelector('.sub-tab[data-tab="access"]').click();
      loadUserAccess(userId, btn.closest("tr")._userData);
      return;
    }

    if (action === "modify") {
      var tr = btn.closest("tr");
      showEditRow(tr, tr._userData);
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
    if (!window.confirm(labels[action] + " this user?")) return;

    btn.disabled = true;
    A.authFetch("/compute/api/auth/admin/users/" + userId, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (result) {
        if (result.ok) { loadUsers(); }
        else { alert(result.data.error || "Action failed."); btn.disabled = false; }
      })
      .catch(function () { alert("Network error."); btn.disabled = false; });
  });

  // ---- Inline edit (Modify button) ----

  function showEditRow(tr, u) {
    var origHTML = tr.innerHTML;
    var self = isCurrentUser(u);
    var gpuChecked = u.allow_gpu_use ? " checked" : "";

    tr.innerHTML =
      '<td class="col-select">—</td>' +
      '<td><input type="email" class="text-input edit-input" id="editEmail" value="' + escapeHtml(u.email || "") + '"></td>' +
      '<td class="muted">—</td>' +
      '<td><input type="text" class="text-input edit-input" id="editFullName" value="' + escapeHtml(u.full_name || "") + '" maxlength="128"></td>' +
      '<td><input type="text" class="text-input edit-input" id="editAffiliation" value="' + escapeHtml(u.affiliation || "") + '"></td>' +
      '<td><select class="text-input edit-input" id="editPosition">' + buildPositionOptions(u.position) + '</select></td>' +
      '<td><input type="text" class="text-input edit-input" id="editPiName" value="' + escapeHtml(u.pi_name || "") + '" maxlength="128"></td>' +
      '<td><select class="text-input edit-input" id="editRole">' +
        '<option value="admin"' + ((u.role || "user") === "admin" ? " selected" : "") + (self ? " disabled" : "") + '>Admin</option>' +
        '<option value="user"' + ((u.role || "user") === "user" ? " selected" : "") + '>User</option>' +
        '<option value="guest"' + ((u.role || "user") === "guest" ? " selected" : "") + '>Guest</option>' +
      '</select></td>' +
      '<td><label class="gpu-toggle"><input type="checkbox" class="edit-input" id="editGpu"' + gpuChecked + '> GPU</label></td>' +
      '<td><select class="text-input edit-input" id="editRegStatus">' +
        '<option value="approved"' + (u.registration_status === "approved" ? " selected" : "") + '>Approved</option>' +
        '<option value="rejected"' + (u.registration_status === "rejected" ? " selected" : "") + '>Rejected</option>' +
      '</select></td>' +
      '<td><select class="text-input edit-input" id="editUserStatus">' +
        '<option value="active"' + (u.user_status === "active" ? " selected" : "") + '>Active</option>' +
        '<option value="banned"' + (u.user_status === "banned" ? " selected" : "") + (self ? " disabled" : "") + '>Banned</option>' +
      '</select></td>' +
      '<td>' +
        '<button class="user-action-btn approve edit-save" data-id="' + u.id + '">Save</button>' +
        '<button class="user-action-btn reject edit-cancel">Cancel</button>' +
      '</td>';
    // Append password row
    var pwRow = document.createElement("tr");
    pwRow.className = "edit-row";
    pwRow.innerHTML =
      '<td></td>' +
      '<td colspan="2"><input type="password" class="text-input edit-input" id="editPassword" placeholder="New password (leave empty to keep)" minlength="8" autocomplete="new-password"></td>' +
      '<td colspan="9" class="muted" style="font-size:0.76rem">Leave blank to keep current password</td>';
    tr.parentNode.insertBefore(pwRow, tr.nextSibling);

    tr._origHTML = origHTML;
    tr._editPwRow = pwRow;

    // Save handler
    tr.querySelector(".edit-save").addEventListener("click", function () {
      var payload = {
        email: document.getElementById("editEmail").value.trim(),
        full_name: document.getElementById("editFullName").value.trim(),
        affiliation: document.getElementById("editAffiliation").value.trim(),
        position: document.getElementById("editPosition").value || null,
        pi_name: document.getElementById("editPiName").value.trim(),
        role: document.getElementById("editRole").value,
        allow_gpu_use: document.getElementById("editGpu").checked,
        registration_status: document.getElementById("editRegStatus").value,
        user_status: document.getElementById("editUserStatus").value,
      };
      // The role selector is display-only for the signed-in administrator.
      // Do not send an immutable field with otherwise valid profile/GPU edits.
      if (self) delete payload.role;
      var pw = document.getElementById("editPassword").value;
      if (pw) payload.password = pw;
      if (self && payload.user_status === "banned") {
        alert("You cannot ban your own account.");
        return;
      }

      A.authFetch("/compute/api/auth/admin/users/" + u.id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (result) {
          if (result.ok) { loadUsers(); }
          else { alert(result.data.error || "Update failed."); }
        })
        .catch(function () { alert("Network error."); });
    });

    // Cancel handler
    tr.querySelector(".edit-cancel").addEventListener("click", function () {
      cancelEdit(tr);
    });
  }

  function cancelEdit(tr) {
    if (tr._editPwRow) { tr._editPwRow.remove(); tr._editPwRow = null; }
    if (tr._origHTML) { tr.innerHTML = tr._origHTML; tr._origHTML = null; }
    // Re-attach checkbox listener
    var cb = tr.querySelector(".user-select");
    if (cb) cb.addEventListener("change", updateBatchBar);
  }

  // ---- Runner access ----

  var accessQueue = document.getElementById("accessRequestQueue");
  var accessPolicyOverview = document.getElementById("accessPolicyOverview");
  var accessActivity = document.getElementById("accessActivity");
  var accessPanel = document.getElementById("userAccessPanel");
  var accessDialog = document.getElementById("accessDecisionDialog");
  var accessTarget = null;

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
          approve.addEventListener("click", function () { openAccessDialog({ requestId: item.id }); });
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
          accessPolicyOverview.appendChild(row);
        });
      })
      .catch(function () { accessPolicyOverview.innerHTML = '<p class="empty error">Failed to load policy overview.</p>'; });
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
          copy.append(title, state); row.appendChild(copy);
          if (!policy.granted) {
            var grant = document.createElement("button"); grant.className = "btn btn-soft"; grant.textContent = "Grant";
            grant.addEventListener("click", function () { openAccessDialog({ userId: userId, entitlement: policy.missing_entitlements[0], user: user }); });
            row.appendChild(grant);
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

  function openAccessDialog(target) {
    accessTarget = target;
    document.getElementById("accessDecisionTitle").textContent = target.requestId ? "Approve access request" : "Grant Runner access";
    document.getElementById("accessDecisionForm").reset(); accessDialog.showModal();
  }

  document.getElementById("accessDecisionForm").addEventListener("submit", function (event) {
    if (event.submitter.value === "cancel") return;
    event.preventDefault();
    var expiry = document.getElementById("accessExpiry").value;
    var payload = {
      basis: document.getElementById("accessBasis").value,
      expires_at: expiry ? new Date(expiry).getTime() / 1000 : null,
      note: document.getElementById("accessNote").value.trim() || null,
    };
    var url;
    if (accessTarget.requestId) { url = "/compute/api/auth/admin/access/requests/" + accessTarget.requestId + "/decision"; payload.decision = "approved"; }
    else { url = "/compute/api/auth/admin/users/" + accessTarget.userId + "/entitlements"; payload.entitlement = accessTarget.entitlement; }
    A.authFetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.error); }); })
      .then(function () { accessDialog.close(); loadAccessRequests(); if (accessTarget.userId) loadUserAccess(accessTarget.userId, accessTarget.user); })
      .catch(function (error) { alert(error.message || "Access update failed."); });
  });

  function rejectAccessRequest(requestId) {
    var note = window.prompt("Optional rejection note:", ""); if (note === null) return;
    A.authFetch("/compute/api/auth/admin/access/requests/" + requestId + "/decision", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "rejected", note: note || null }),
    }).then(function (r) { if (!r.ok) throw new Error(); loadAccessRequests(); }).catch(function () { alert("Rejection failed."); });
  }

  function revokeGrant(userId, grantId, user) {
    if (!window.confirm("Revoke this Runner entitlement for future submissions?")) return;
    A.authFetch("/compute/api/auth/admin/users/" + userId + "/entitlements/" + grantId + "/revoke", { method: "POST" })
      .then(function (r) { if (!r.ok) throw new Error(); loadUserAccess(userId, user); })
      .catch(function () { alert("Revocation failed."); });
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

  // Initial load
  loadCurrentUser()
    .catch(function () { currentUsername = null; })
    .then(loadUsers);
})();
