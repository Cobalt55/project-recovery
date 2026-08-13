(() => {
  const SETTINGS_LINK_ID = "project-recovery-settings-link";
  const CONTROL_LABELS = {
    "#sidebar-trigger-button": "Open conversation history",
    "#search-chats-button": "Search conversations",
    "#new-chat-button": "New chat",
    "#sidebar-open": "Sidebar",
    "#sidebar-close": "Close sidebar",
    "#thread-search": "Search conversations",
    "#new-chat": "New chat",
    "#upload-button": "Attach files",
    "#chat-settings-open-modal": "Chat settings",
    "#chat-submit": "Send message",
    "#stop-button": "Stop response",
    "#user-nav-button": "Account menu",
    "[data-testid='user-menu']": "Account menu",
  };
  const SUBMIT_TRANSITION_MS = 900;
  let suppressStopUntil = 0;

  const matching = (root, selector) => {
    const nodes = [];
    if (root instanceof Element && root.matches(selector)) nodes.push(root);
    if (root.querySelectorAll) nodes.push(...root.querySelectorAll(selector));
    return nodes;
  };
  const mountSettingsLink = () => {
    if (document.getElementById(SETTINGS_LINK_ID)) return;
    const link = document.createElement("a");
    link.id = SETTINGS_LINK_ID;
    link.href = "/settings";
    link.setAttribute("aria-label", "Settings");
    link.setAttribute("data-testid", "chat-settings-link");
    link.innerHTML = [
      '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor">',
      '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.72l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>',
      '<circle cx="12" cy="12" r="3"></circle>',
      "</svg>",
      '<span data-pr-settings-label>Settings</span>',
    ].join("");
    document.body.appendChild(link);
  };

  const labelNativeControls = (root) => {
    for (const [selector, label] of Object.entries(CONTROL_LABELS)) {
      matching(root, selector).forEach((control) => {
        if (!control.getAttribute("aria-label")) control.setAttribute("aria-label", label);
        if (control.getAttribute("role") === "presentation") control.removeAttribute("role");
        control.dataset.prEnhanced = "true";
        control.setAttribute("data-pr-enhanced", "true");
      });
    }
  };

  const improveHistory = (root) => {
    matching(root, "a[href*='/thread/'] button, a[href*='/threads/'] button").forEach((button) => {
      const link = button.closest("a[href]");
      const linkName = (link?.getAttribute("aria-label") || link?.textContent || "").trim();
      const buttonName = (button.getAttribute("aria-label") || button.textContent || "").trim();
      if (!linkName || !buttonName || linkName !== buttonName) return;
      button.setAttribute("tabindex", "-1");
      button.setAttribute("aria-hidden", "true");
      button.dataset.prEnhanced = "true";
      button.setAttribute("data-pr-enhanced", "true");
    });
  };

  let dialogSequence = 0;
  const improveDialogs = (root) => {
    matching(root, "[role=dialog]").forEach((dialog) => {
      const title = dialog.querySelector("h1, h2, [data-slot='dialog-title']");
      const description = dialog.querySelector("p, [data-slot='dialog-description']");
      const dialogId = dialog.id || `pr-dialog-${dialogSequence += 1}`;
      if (!dialog.id) dialog.id = dialogId;
      if (title) {
        if (!title.id) title.id = `${dialogId}-title`;
        dialog.setAttribute("aria-labelledby", title.id);
      }
      if (description) {
        if (!description.id) description.id = `${dialogId}-description`;
        dialog.setAttribute("aria-describedby", description.id);
      }
    });
  };

  const protectSubmit = (root) => {
    matching(root, "#chat-submit").forEach((submit) => {
      if (submit.dataset.prSubmitGuard === "true") return;
      submit.dataset.prSubmitGuard = "true";
      submit.addEventListener(
        "click",
        (event) => {
          if (!submit.matches("#chat-submit")) return;
          if (submit.dataset.prSubmitting === "true") {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
          }
          submit.dataset.prSubmitting = "true";
          submit.setAttribute("data-pr-submitting", "true");
          submit.setAttribute("aria-label", "Sending message");
          suppressStopUntil = Date.now() + SUBMIT_TRANSITION_MS;
          window.setTimeout(() => {
            delete submit.dataset.prSubmitting;
            submit.removeAttribute("data-pr-submitting");
            if (document.contains(submit)) submit.setAttribute("aria-label", "Send message");
          }, SUBMIT_TRANSITION_MS);
        },
        true,
      );
    });
  };

  function enhance(root) {
    if (!(root instanceof Element || root === document)) return;
    labelNativeControls(root);
    improveHistory(root);
    improveDialogs(root);
    protectSubmit(root);
    matching(root, "#chat-submit").forEach((submit) => {
      if (
        submit.dataset.prSubmitting !== "true" &&
        submit.getAttribute("aria-label") !== "Send message"
      ) {
        submit.setAttribute("aria-label", "Send message");
      }
    });
    matching(root, "#stop-button").forEach((stop) => {
      if (stop.getAttribute("aria-label") !== "Stop response") {
        stop.setAttribute("aria-label", "Stop response");
      }
      stop.dataset.prEnhanced = "true";
      stop.setAttribute("data-pr-enhanced", "true");
    });
  }

  const start = () => {
    mountSettingsLink();
    enhance(document);
    const observer = new MutationObserver((records) => {
      records.forEach((record) => {
        if (record.type === "attributes" && record.target instanceof Element) {
          enhance(record.target);
          return;
        }
        record.addedNodes.forEach(enhance);
      });
      mountSettingsLink();
    });
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["aria-label", "id", "role"],
      childList: true,
      subtree: true,
    });
    document.addEventListener(
      "click",
      (event) => {
        const target = event.target;
        const stop = target instanceof Element ? target.closest("#stop-button") : null;
        if (!stop || Date.now() >= suppressStopUntil) return;
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      true,
    );
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
