"use strict";

document.documentElement.classList.add("js-ready");

(() => {
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const message = form.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  const copyStatus = document.createElement("p");
  copyStatus.className = "sr-only";
  copyStatus.setAttribute("aria-live", "polite");
  copyStatus.setAttribute("role", "status");
  document.body.append(copyStatus);
  const announceCopyStatus = (message) => {
    copyStatus.textContent = "";
    window.requestAnimationFrame(() => {
      copyStatus.textContent = message;
    });
  };
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-value]");
    if (!(button instanceof HTMLButtonElement)) return;
    const value = button.dataset.copyValue || "";
    try {
      await navigator.clipboard.writeText(value);
      announceCopyStatus("Copied to clipboard.");
    } catch {
      announceCopyStatus("Copy unavailable. Select the value to copy it.");
    }
  });

  try {
    const formatter = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    document.querySelectorAll("time[data-local-time]").forEach((element) => {
      const exact = element.getAttribute("datetime");
      const date = exact ? new Date(exact) : null;
      if (date && !Number.isNaN(date.getTime())) element.textContent = formatter.format(date);
    });
  } catch {
    // Keep the server-rendered UTC value if browser localization is unavailable.
  }

  const opener = document.querySelector("[data-drawer-open]");
  const drawer = document.querySelector("[data-drawer]");
  const backdrop = document.querySelector("[data-drawer-backdrop]");
  const closeButton = document.querySelector("[data-drawer-close]");

  if (!opener || !drawer || !backdrop || !closeButton) return;

  const focusableSelector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  const setOpen = (open, restoreFocus = false) => {
    drawer.hidden = !open;
    backdrop.hidden = !open;
    drawer.setAttribute("aria-hidden", String(!open));
    backdrop.setAttribute("aria-hidden", String(!open));
    opener.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("drawer-open", open);
    if (open) closeButton.focus();
    if (!open && restoreFocus) opener.focus();
  };

  opener.addEventListener("click", () => setOpen(true));
  closeButton.addEventListener("click", () => setOpen(false, true));
  backdrop.addEventListener("click", () => setOpen(false, true));
  document.addEventListener("keydown", (event) => {
    if (drawer.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false, true);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...drawer.querySelectorAll(focusableSelector)];
    const first = focusable[0] || drawer;
    const last = focusable[focusable.length - 1] || drawer;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
})();
