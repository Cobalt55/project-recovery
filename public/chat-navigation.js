(() => {
  const NAV_ID = "project-recovery-nav";
  const TOGGLE_ID = "project-recovery-nav-toggle";
  const BACKDROP_ID = "project-recovery-nav-backdrop";
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
  const mobileQuery = window.matchMedia("(max-width: 900px)");

  const isMobile = () => mobileQuery.matches;
  const matching = (root, selector) => {
    const nodes = [];
    if (root instanceof Element && root.matches(selector)) nodes.push(root);
    if (root.querySelectorAll) nodes.push(...root.querySelectorAll(selector));
    return nodes;
  };
  const drawerFocusable = (nav) => [
    ...nav.querySelectorAll("button:not([disabled]), a[href]")
  ].filter((element) => {
    const style = window.getComputedStyle(element);
    return (
      !element.hidden &&
      element.getAttribute("aria-hidden") !== "true" &&
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      element.getClientRects().length > 0
    );
  });

  const setDrawer = (open, { restoreFocus = true } = {}) => {
    const nav = document.getElementById(NAV_ID);
    const toggle = document.getElementById(TOGGLE_ID);
    const backdrop = document.getElementById(BACKDROP_ID);
    if (!nav || !toggle || !backdrop) return;
    const visible = isMobile() && open;
    nav.dataset.prDrawerOpen = String(visible);
    nav.setAttribute("data-pr-drawer-open", String(visible));
    nav.setAttribute("aria-hidden", String(isMobile() && !visible));
    nav.toggleAttribute("inert", isMobile() && !visible);
    backdrop.hidden = !visible;
    backdrop.setAttribute("aria-hidden", String(!visible));
    document.body.dataset.prDrawerOpen = String(visible);
    toggle.setAttribute("aria-expanded", String(visible));
    if (visible) {
      nav.querySelector("[data-pr-drawer-close]")?.focus();
    } else if (restoreFocus && isMobile()) {
      toggle.focus();
    }
  };

  const renderNavigation = (items) => {
    if (document.getElementById(NAV_ID)) return;
    const backdrop = document.createElement("div");
    backdrop.id = BACKDROP_ID;
    backdrop.hidden = true;
    backdrop.setAttribute("aria-hidden", "true");
    const nav = document.createElement("nav");
    nav.id = NAV_ID;
    nav.setAttribute("aria-label", "Project Recovery workspace");
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
    toggle.setAttribute("data-pr-drawer-open", "true");
    toggle.setAttribute("aria-controls", NAV_ID);
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open workspace navigation");
    toggle.textContent = "Menu";
    document.body.append(toggle, backdrop, nav);
    toggle.addEventListener("click", () => setDrawer(true));
    nav.querySelector("[data-pr-drawer-close]").addEventListener("click", () => setDrawer(false));
    backdrop.addEventListener("click", () => setDrawer(false));
    setDrawer(false, { restoreFocus: false });
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
    if (!(root instanceof Element || root === document)) return;
    labelNativeControls(root);
    improveHistory(root);
    improveDialogs(root);
    protectSubmit(root);
    matching(root, "#stop-button").forEach((stop) => {
      stop.setAttribute("aria-label", "Stop response");
      stop.dataset.prEnhanced = "true";
      stop.setAttribute("data-pr-enhanced", "true");
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
        return;
      }
    } catch {
      // A direct Chainlit login still receives the safe personal destinations.
    }
    renderNavigation([
      { label: "Chat", href: "/chat" },
      { label: "Settings", href: "/settings" },
    ]);
  };

  const start = () => {
    load();
    enhance(document);
    const observer = new MutationObserver((records) => {
      records.forEach((record) => {
        if (record.type === "attributes" && record.target instanceof Element) {
          enhance(record.target);
          return;
        }
        record.addedNodes.forEach(enhance);
      });
    });
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["aria-label", "role"],
      childList: true,
      subtree: true,
    });
    document.addEventListener("keydown", (event) => {
      const nav = document.getElementById(NAV_ID);
      if (
        !nav ||
        !isMobile() ||
        nav.dataset.prDrawerOpen !== "true" ||
        nav.getAttribute("aria-hidden") === "true"
      ) {
        return;
      }
      if (event.key === "Escape") {
        setDrawer(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = drawerFocusable(nav);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    mobileQuery.addEventListener("change", () => setDrawer(false, { restoreFocus: false }));
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
