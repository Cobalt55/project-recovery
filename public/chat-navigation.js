(() => {
  const NAV_ID = "project-recovery-nav";

  const render = (items) => {
    if (document.getElementById(NAV_ID)) return;
    const nav = document.createElement("nav");
    nav.id = NAV_ID;
    nav.setAttribute("aria-label", "Workspace");
    for (const item of items) {
      const link = document.createElement("a");
      link.href = item.href;
      link.textContent = item.label;
      nav.appendChild(link);
    }
    document.body.appendChild(nav);
  };

  const load = async () => {
    try {
      const response = await fetch("/api/navigation", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (response.ok) {
        const payload = await response.json();
        render(payload.items || []);
        return;
      }
    } catch {
      // A direct Chainlit login still receives the safe personal destinations.
    }
    render([
      { label: "Chat", href: "/chat" },
      { label: "Settings", href: "/settings" },
    ]);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load, { once: true });
  } else {
    load();
  }
})();
