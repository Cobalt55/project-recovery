(() => {
  const NAV_ID = "project-recovery-nav";
  const TOGGLE_ID = "project-recovery-nav-toggle";
  const CONTROL_LABELS = {
    "#sidebar-open": "Sidebar",
    "#sidebar-close": "Close sidebar",
    "#thread-search": "Search conversations",
    "#new-chat": "New chat",
    "#upload-button": "Attach files",
    "#chat-settings-open-modal": "Chat settings",
    "#chat-submit": "Send message",
    "#stop-button": "Stop response",
    "[data-testid='user-menu']": "Account menu",
  };

  const isMobile = () => window.matchMedia("(max-width: 900px)").matches;

  const setDrawer = (open) => {
    const nav = document.getElementById(NAV_ID);
    const toggle = document.getElementById(TOGGLE_ID);
    if (!nav || !toggle) return;
    nav.dataset.prDrawerOpen = String(open);
    nav.setAttribute("data-pr-drawer-open", String(open));
    document.body.dataset.prDrawerOpen = String(open);
    toggle.setAttribute("aria-expanded", String(open));
    if (open && isMobile()) {
      nav.querySelector("[data-pr-drawer-close]")?.focus();
    } else if (!open) {
      toggle.focus();
    }
  };

  const renderNavigation = (items) => {
    if (document.getElementById(NAV_ID)) return;
    const nav = document.createElement("nav");
    nav.id = NAV_ID;
    nav.setAttribute("aria-label", "Project Recovery workspace");
    nav.dataset.prDrawerOpen = "false";
    nav.setAttribute("data-pr-drawer-open", "false");
    nav.innerHTML = [
      '<div data-pr-brand>Project Recovery</div>',
      '<button type="button" data-pr-drawer-close aria-label="Close workspace navigation">Close</button>',
      '<div data-pr-nav-links></div>',
    ].join("");
    const links = nav.querySelector("[data-pr-nav-links]");
    for (const item of items) {
      const link = document.createElement("a");
      link.href = item.href;
      link.textContent = item.label;
      if (item.active || window.location.pathname === item.href) {
        link.setAttribute("aria-current", "page");
      }
      links.appendChild(link);
    }

    const toggle = document.createElement("button");
    toggle.id = TOGGLE_ID;
    toggle.type = "button";
    toggle.dataset.prWorkspaceToggle = "true";
    toggle.dataset.prDrawerOpen = "true";
    toggle.setAttribute("data-pr-drawer-open", "true");
    toggle.setAttribute("aria-controls", NAV_ID);
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open workspace navigation");
    toggle.textContent = "Menu";
    document.body.append(toggle, nav);
    toggle.addEventListener("click", () => setDrawer(true));
    nav.querySelector("[data-pr-drawer-close]").addEventListener("click", () => setDrawer(false));
    nav.addEventListener("click", (event) => {
      if (event.target === nav && isMobile()) setDrawer(false);
    });
  };

  const labelNativeControls = (root) => {
    for (const [selector, label] of Object.entries(CONTROL_LABELS)) {
      root.querySelectorAll(selector).forEach((control) => {
        if (!control.getAttribute("aria-label")) control.setAttribute("aria-label", label);
        control.dataset.prEnhanced = "true";
        control.setAttribute("data-pr-enhanced", "true");
      });
    }
  };

  const improveHistory = (root) => {
    root.querySelectorAll("a[href*='/thread/'] button, a[href*='/threads/'] button").forEach((button) => {
      button.setAttribute("tabindex", "-1");
      button.setAttribute("aria-hidden", "true");
      button.dataset.prEnhanced = "true";
      button.setAttribute("data-pr-enhanced", "true");
    });
  };

  const improveDialogs = (root) => {
    root.querySelectorAll("[role=dialog]").forEach((dialog) => {
      const title = dialog.querySelector("h1, h2, [data-slot='dialog-title']");
      const description = dialog.querySelector("p, [data-slot='dialog-description']");
      if (title) {
        if (!title.id) title.id = "pr-dialog-title";
        dialog.setAttribute("aria-labelledby", title.id);
      }
      if (description) {
        if (!description.id) description.id = "pr-dialog-description";
        dialog.setAttribute("aria-describedby", description.id);
      }
    });
  };

  const protectSubmit = (root) => {
    root.querySelectorAll("#chat-submit").forEach((submit) => {
      if (submit.dataset.prEnhanced) return;
      submit.dataset.prEnhanced = "true";
      submit.setAttribute("data-pr-enhanced", "true");
      submit.addEventListener(
        "click",
        (event) => {
          if (submit.dataset.prSubmitting === "true") {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
          }
          submit.dataset.prSubmitting = "true";
          submit.setAttribute("data-pr-submitting", "true");
          submit.setAttribute("aria-label", "Sending message");
          window.setTimeout(() => {
            delete submit.dataset.prSubmitting;
            submit.removeAttribute("data-pr-submitting");
            if (document.contains(submit)) submit.setAttribute("aria-label", "Send message");
          }, 900);
        },
        true,
      );
    });
  };

  function enhance(root) {
    labelNativeControls(root);
    improveHistory(root);
    improveDialogs(root);
    protectSubmit(root);
    root.querySelectorAll("#stop-button").forEach((stop) => {
      stop.setAttribute("aria-label", "Stop response");
      stop.dataset.prEnhanced = "true";
      stop.setAttribute("data-pr-enhanced", "true");
    });
    root.querySelectorAll("h1, h2, p, span").forEach((element) => {
      if (element.childElementCount) return;
      if (element.textContent.trim() === "Chainlit") element.textContent = "Project Recovery";
      if (element.textContent.trim() === "How can I help you today?") {
        element.textContent = "Ask a grounded question to get started.";
      }
    });
  }

  const load = async () => {
    try {
      const response = await fetch("/api/navigation", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (response.ok) {
        const payload = await response.json();
        renderNavigation(payload.items || []);
      } else {
        renderNavigation([]);
      }
    } catch {
      renderNavigation([
        { label: "Chat", href: "/chat" },
        { label: "Settings", href: "/settings" },
      ]);
    }
  };

  const start = () => {
    load();
    enhance(document);
    const observer = new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) enhance(node);
      }));
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && document.body.dataset.prDrawerOpen === "true") {
        setDrawer(false);
      }
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
