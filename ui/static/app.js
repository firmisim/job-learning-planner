const messagePayload = document.querySelector("#ui-messages")?.textContent;
const uiMessages = messagePayload ? JSON.parse(messagePayload) : {};

function uiMessage(key) {
  const value = uiMessages[key];
  if (typeof value !== "string") throw new Error(`Missing UI message: ${key}`);
  return value;
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.checkValidity()) return;
  const confirmation = form.dataset.confirm;
  const conditionalField = form.dataset.confirmWhen;
  if (confirmation && (!conditionalField || form.elements[conditionalField]?.checked)) {
    if (!window.confirm(confirmation)) {
      event.preventDefault();
      return;
    }
  }
  const submitter = event.submitter;
  if (submitter instanceof HTMLButtonElement && submitter.name) {
    const submittedValue = document.createElement("input");
    submittedValue.type = "hidden";
    submittedValue.name = submitter.name;
    submittedValue.value = submitter.value;
    submittedValue.dataset.submittedButtonValue = "true";
    form.append(submittedValue);
  }
  form.setAttribute("aria-busy", "true");
  form.querySelectorAll("button[type='submit']").forEach((button) => {
    button.dataset.wasDisabled = String(button.disabled);
    button.disabled = true;
    button.dataset.originalLabel = button.textContent;
    button.textContent = button.dataset.workingLabel || uiMessage("common.working");
  });
});

function restoreSubmitControls(element) {
  const form = element instanceof HTMLFormElement ? element : element?.closest?.("form");
  if (!form) return;
  form.removeAttribute("aria-busy");
  form.querySelectorAll("[data-submitted-button-value]").forEach((field) => field.remove());
  form.querySelectorAll("[data-bulk-persisted-item]").forEach((field) => field.remove());
  form.querySelectorAll("button[type='submit']").forEach((button) => {
    button.disabled = button.dataset.wasDisabled === "true";
    delete button.dataset.wasDisabled;
    if (button.dataset.originalLabel) {
      button.textContent = button.dataset.originalLabel;
      delete button.dataset.originalLabel;
    }
  });
}

document.addEventListener("htmx:beforeRequest", (event) => {
  event.detail.elt?.setAttribute("aria-busy", "true");
});

document.addEventListener("htmx:beforeSwap", (event) => {
  const response = event.detail.xhr;
  if (response.status >= 400 && response.getResponseHeader("HX-Retarget")) {
    event.detail.shouldSwap = true;
  }
});

document.addEventListener("htmx:afterRequest", (event) => {
  restoreSubmitControls(event.detail.elt);
});

document.addEventListener("htmx:responseError", (event) => {
  restoreSubmitControls(event.detail.elt);
});

document.addEventListener("htmx:sendError", (event) => {
  restoreSubmitControls(event.detail.elt);
});

function initializeDecisionForms(root = document) {
  root.querySelectorAll("[data-decision-form]").forEach((form) => {
    if (form.dataset.decisionReady) return;
    form.dataset.decisionReady = "true";
    const select = form.querySelector("[data-decision-select]");
    const update = () => {
      form.querySelectorAll("[data-for-decision]").forEach((section) => {
        const active = section.dataset.forDecision === select.value;
        section.hidden = !active;
        section.querySelectorAll("input, select, textarea").forEach((field) => {
          field.disabled = !active;
        });
      });
    };
    select.addEventListener("change", update);
    update();
  });
}

function initializeBulkForms(root = document) {
  root.querySelectorAll("[data-bulk-form]").forEach((form) => {
    if (form.dataset.bulkReady) return;
    form.dataset.bulkReady = "true";
    const items = [...form.querySelectorAll("[data-bulk-item]")];
    const count = form.querySelector("[data-selected-count]");
    const submit = form.querySelector("[data-bulk-submit]");
    const list = form.dataset.selectionList;
    const roleId = form.dataset.selectionRole;
    if (!list || !roleId) {
      const updateCurrentPage = () => {
        const selected = items.filter((item) => item.checked).length;
        if (count) count.textContent = String(selected);
        if (submit) submit.disabled = selected === 0;
      };
      items.forEach((item) => item.addEventListener("change", updateCurrentPage));
      updateCurrentPage();
      return;
    }
    const query = (form.dataset.selectionQuery || "")
      .trim()
      .replace(/\s+/g, " ")
      .toLocaleLowerCase();
    const storageKey = `job-learning-bulk-selection:${list}`;
    const scope = { roleId, list, query };
    let selected = new Set();
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (
        saved?.scope?.roleId === scope.roleId &&
        saved?.scope?.list === scope.list &&
        saved?.scope?.query === scope.query &&
        Array.isArray(saved.selected)
      ) {
        selected = new Set(saved.selected.filter((value) => typeof value === "string"));
      } else {
        sessionStorage.removeItem(storageKey);
      }
      const locationParams = new URLSearchParams(window.location.search);
      if (locationParams.get("selection_cleared") === list) {
        selected.clear();
        sessionStorage.removeItem(storageKey);
        locationParams.delete("selection_cleared");
        const search = locationParams.toString();
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`,
        );
      }
    } catch (error) {
      selected.clear();
    }
    items.forEach((item) => {
      item.checked = selected.has(item.value);
    });
    const persist = () => {
      try {
        if (selected.size) {
          sessionStorage.setItem(
            storageKey,
            JSON.stringify({ scope, selected: [...selected] }),
          );
        } else {
          sessionStorage.removeItem(storageKey);
        }
      } catch (error) {
        // Selection remains available for this rendered page when storage is unavailable.
      }
    };
    const update = () => {
      if (count) count.textContent = String(selected.size);
      if (submit) submit.disabled = selected.size === 0;
    };
    items.forEach((item) => item.addEventListener("change", () => {
      if (item.checked) selected.add(item.value);
      else selected.delete(item.value);
      persist();
      update();
    }));
    form.addEventListener("submit", () => {
      const visible = new Set(items.filter((item) => item.checked).map((item) => item.value));
      selected.forEach((value) => {
        if (visible.has(value)) return;
        const field = document.createElement("input");
        field.type = "hidden";
        field.name = items[0]?.name || "";
        field.value = value;
        field.dataset.bulkPersistedItem = "true";
        form.append(field);
      });
    });
    update();
  });
}

document.querySelectorAll("[data-role-switch]").forEach((form) => {
  form.addEventListener("submit", () => {
    try {
      Object.keys(sessionStorage)
        .filter((key) => key.startsWith("job-learning-bulk-selection:"))
        .forEach((key) => sessionStorage.removeItem(key));
    } catch (error) {
      // A Role change still gets a clean scope when the next page initializes.
    }
  });
});

initializeBulkForms();
initializeDecisionForms();
document.addEventListener("htmx:load", (event) => {
  initializeBulkForms(event.detail.elt);
  initializeDecisionForms(event.detail.elt);
});
