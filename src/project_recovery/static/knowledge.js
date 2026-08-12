(() => {
  for (const form of document.querySelectorAll("[data-confirm-delete]")) {
    form.addEventListener("submit", (event) => {
      if (!window.confirm("Delete this Knowledge resource? This cannot be undone.")) {
        event.preventDefault();
      }
    });
  }

  const table = document.querySelector("[data-knowledge-table]");
  if (!table) return;
  const poll = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch("/admin/knowledge/status", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      for (const item of payload.items || []) {
        const row = table.querySelector(`[data-resource-id="${CSS.escape(item.id)}"]`);
        const status = row?.querySelector("[data-resource-status]");
        if (status) status.textContent = item.status;
      }
    } catch {
      // Preserve the last known state; the next interval retries.
    }
  };
  window.setInterval(poll, 5000);
})();
