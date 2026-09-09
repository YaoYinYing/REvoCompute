/* SPDX-License-Identifier: GPL-3.0-only */
(function () {
  "use strict";

  var link = document.getElementById("agentSkillsUrl");
  var button = document.getElementById("copyAgentSkillsUrl");
  var status = document.getElementById("agentCopyStatus");
  if (!link || !button || !status) return;

  var url = new URL(link.dataset.path, window.location.origin).href;
  link.querySelector("code").textContent = url;

  button.addEventListener("click", function () {
    navigator.clipboard.writeText(url).then(function () {
      button.textContent = "Copied";
      status.textContent = "Agent API guide URL copied.";
      window.setTimeout(function () {
        button.textContent = "Copy";
        status.textContent = "";
      }, 2000);
    }, function () {
      status.textContent = "Select the URL to copy it manually.";
      link.focus();
    });
  });
})();
