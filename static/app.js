const ui = {
  addItem: document.querySelector("#add-item"),
  approve: document.querySelector("#approve-button"),
  copy: document.querySelector("#copy-result"),
  fetch: document.querySelector("#fetch-button"),
  form: document.querySelector("#review-form"),
  invoiceList: document.querySelector("#invoice-list"),
  invoicePanel: document.querySelector("#invoice-panel"),
  items: document.querySelector("#items-body"),
  noItems: document.querySelector("#no-items"),
  preview: document.querySelector("#document-preview"),
  process: document.querySelector("#process-button"),
  processing: document.querySelector("#processing-card"),
  processingError: document.querySelector("#processing-error"),
  processingSubtitle: document.querySelector("#processing-subtitle"),
  processingTitle: document.querySelector("#processing-title"),
  progressBar: document.querySelector("#progress-bar"),
  progressValue: document.querySelector("#progress-value"),
  rawText: document.querySelector("#raw-text"),
  result: document.querySelector("#result-card"),
  resultJson: document.querySelector("#result-json"),
  reviewContent: document.querySelector("#review-content"),
  send: document.querySelector("#send-result"),
  selectedLabel: document.querySelector("#selected-label"),
  toast: document.querySelector("#toast"),
  vendor: document.querySelector("#field-vendor"),
  invoiceNo: document.querySelector("#field-invoice"),
  invoiceState: document.querySelector("#field-state"),
};

const state = {
  invoices: new Map(),
  items: [],
  selectedId: null,
  sources: [],
  toastTimeout: null,
};

const progressStages = {
  queued: ["Starting OCR", "Preparing the selected invoice.", 5],
  downloading: ["Fetching invoice", "Loading the source document.", 20],
  recognizing: ["Reading invoice", "OCR is recognizing the text in the document.", 58],
  extracting: ["Extracting details", "Organizing the text into invoice fields.", 84],
  completed: ["OCR complete", "The extracted details are ready for your review.", 100],
  failed: ["OCR could not finish", "Check the message below and try again.", 100],
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  let body;
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) {
    const detail = body.detail;
    const message = Array.isArray(detail)
      ? detail.map((entry) => entry.msg).join("; ")
      : detail;
    throw new Error(message || `Request failed (${response.status})`);
  }
  return body;
}

function notify(message, error = false) {
  window.clearTimeout(state.toastTimeout);
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", error);
  ui.toast.classList.add("visible");
  state.toastTimeout = window.setTimeout(
    () => ui.toast.classList.remove("visible"),
    3500,
  );
}

function setStep(step) {
  const sequence = ["fetch", "review", "approve"];
  const active = sequence.indexOf(step);
  document.querySelectorAll(".stepper-item").forEach((item) => {
    const index = sequence.indexOf(item.dataset.step);
    item.classList.toggle("active", active === index);
    item.classList.toggle("complete", active > index);
  });
}

function getSourceStatus(source) {
  const invoice = source.invoice_id && state.invoices.get(source.invoice_id);
  return invoice ? invoice.status : source.status || "available";
}

function renderSources() {
  ui.invoiceList.replaceChildren();
  if (!state.sources.length) {
    const empty = document.createElement("p");
    empty.className = "list-empty";
    empty.textContent = "Click “Fetch invoices” to get started.";
    ui.invoiceList.append(empty);
    return;
  }

  for (const source of state.sources) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "invoice-card";
    button.setAttribute("aria-current", String(source.id === state.selectedId));
    button.innerHTML = `
      <span class="invoice-file-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20"><path d="M4.5 2.5h7l4 4v11h-11zM11.5 2.5v4h4M7.5 10h5M7.5 13h5"/></svg>
      </span>
      <span><strong></strong><small></small></span>
      <i class="status-dot ${getSourceStatus(source)}" aria-hidden="true"></i>`;
    button.querySelector("strong").textContent = source.id;
    button.querySelector("small").textContent = source.file_type || "Invoice";
    button.addEventListener("click", () => selectInvoice(source.id));
    ui.invoiceList.append(button);
  }
}

function renderItems(disabled = false) {
  ui.items.replaceChildren();
  state.items.forEach((item, index) => {
    const row = document.createElement("tr");
    const description = document.createElement("input");
    description.className = "item-input";
    description.type = "text";
    description.value = item.material_description || "";
    description.placeholder = "Description";
    description.required = true;
    description.disabled = disabled;
    description.setAttribute("aria-label", `Item ${index + 1} description`);
    description.addEventListener("input", () => {
      state.items[index].material_description = description.value;
    });

    const quantity = document.createElement("input");
    quantity.className = "item-input numeric";
    quantity.type = "number";
    quantity.min = "0";
    quantity.step = "any";
    quantity.value = item.quantity ?? "";
    quantity.required = true;
    quantity.disabled = disabled;
    quantity.setAttribute("aria-label", `Item ${index + 1} quantity`);
    quantity.addEventListener("input", () => {
      state.items[index].quantity = quantity.value;
    });

    const price = document.createElement("input");
    price.className = "item-input numeric";
    price.type = "number";
    price.min = "0";
    price.step = "any";
    price.value = item.price ?? "";
    price.required = true;
    price.disabled = disabled;
    price.setAttribute("aria-label", `Item ${index + 1} unit price`);
    price.addEventListener("input", () => {
      state.items[index].price = price.value;
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-item";
    remove.textContent = "x";
    remove.disabled = disabled;
    remove.title = "Remove line item";
    remove.setAttribute("aria-label", `Remove item ${index + 1}`);
    remove.addEventListener("click", () => {
      state.items.splice(index, 1);
      renderItems();
    });

    for (const [element, className] of [
      [description, "description-cell"],
      [quantity, "quantity-cell"],
      [price, "price-cell"],
      [remove, "action-cell"],
    ]) {
      const cell = document.createElement("td");
      cell.className = className;
      cell.append(element);
      row.append(cell);
    }
    ui.items.append(row);
  });
  ui.noItems.hidden = state.items.length > 0;
}

function showInvoice(invoice) {
  state.invoices.set(invoice.id, invoice);
  state.items = invoice.draft.items.map((item) => ({ ...item }));
  ui.vendor.value = invoice.draft.vendor_name || "";
  ui.invoiceNo.value = invoice.draft.invoice_no || "";
  ui.invoiceState.value = invoice.draft.invoice_state || "";
  ui.rawText.textContent = invoice.raw_text || "No text was recognized.";
  ui.reviewContent.hidden = false;
  ui.processing.hidden = true;
  ui.result.hidden = invoice.status !== "approved";
  ui.resultJson.hidden = true;
  ui.copy.hidden = true;

  const editable = invoice.status === "needs_review";
  if (invoice.status === "approved") {
    ui.resultJson.textContent = JSON.stringify(invoice.draft, null, 2);
    ui.resultJson.hidden = false;
    ui.copy.hidden = false;
  }
  for (const input of ui.form.querySelectorAll("input")) input.disabled = !editable;
  ui.addItem.disabled = !editable;
  ui.approve.hidden = !editable;
  ui.process.hidden = invoice.status !== "rejected";
  ui.process.disabled = false;
  ui.process.textContent = invoice.status === "rejected" ? "Run OCR again" : "Run OCR";
  renderItems(!editable);

  if (invoice.status === "approved") {
    setStep("approve");
  } else {
    setStep("review");
  }
  renderSources();
}

function selectInvoice(sourceId) {
  state.selectedId = sourceId;
  ui.invoicePanel.hidden = false;
  ui.selectedLabel.textContent = sourceId;
  ui.preview.src = `/api/source-invoices/${encodeURIComponent(sourceId)}/preview`;
  ui.processing.hidden = true;
  ui.reviewContent.hidden = true;
  ui.process.hidden = false;
  ui.process.disabled = false;
  ui.process.textContent = "Run OCR";
  ui.result.hidden = true;
  ui.approve.hidden = false;
  ui.form.reset();
  ui.items.replaceChildren();
  state.items = [];
  renderSources();
  setStep("fetch");
}

async function fetchInvoices() {
  ui.fetch.disabled = true;
  ui.fetch.textContent = "Fetching...";
  try {
    const response = await request("/api/source-invoices");
    state.sources = response.invoices;
    state.selectedId = null;
    ui.invoicePanel.hidden = true;
    renderSources();
    if (!state.sources.length) {
      notify("No invoices were found.");
      return;
    }

    notify(`Fetched ${state.sources.length} invoices. Select one to continue.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    ui.fetch.disabled = false;
    ui.fetch.textContent = "Fetch invoices";
  }
}

function updateProgress(job) {
  const stage = job.stage || "queued";
  const [title, subtitle, defaultProgress] =
    progressStages[stage] || progressStages.queued;
  const progress = job.progress || defaultProgress;
  ui.processingTitle.textContent = title;
  ui.processingSubtitle.textContent = subtitle;
  ui.progressValue.textContent = `${progress}%`;
  ui.progressBar.style.width = `${progress}%`;
  ui.processingError.hidden = job.status !== "failed";
  if (job.status === "failed") {
    ui.processingError.textContent = job.error || "Unexpected processing error.";
  }
  setStep("review");
}

async function runOcr() {
  const sourceId = state.selectedId;
  if (!sourceId) return;
  ui.process.disabled = true;
  ui.process.textContent = "Starting OCR…";
  ui.processing.hidden = false;
  ui.reviewContent.hidden = true;
  ui.processingError.hidden = true;
  updateProgress({ stage: "queued", progress: 5, status: "queued" });

  try {
    const started = await request(
      `/api/source-invoices/${encodeURIComponent(sourceId)}/process`,
      { method: "POST" },
    );
    if (started.invoice_id) {
      const invoice = await request(`/api/invoices/${encodeURIComponent(started.invoice_id)}`);
      const source = state.sources.find((item) => item.id === sourceId);
      if (source) source.invoice_id = invoice.id;
      showInvoice(invoice);
      return;
    }

    let job;
    do {
      job = await request(`/api/jobs/${encodeURIComponent(started.job_id)}`);
      updateProgress(job);
      if (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 220));
      }
    } while (job.status === "queued" || job.status === "running");

    if (job.status === "failed") {
      ui.process.disabled = false;
      ui.process.textContent = "Try OCR again";
      notify(job.error || "OCR could not process this invoice.", true);
      return;
    }

    const source = state.sources.find((item) => item.id === sourceId);
    if (source) {
      source.invoice_id = job.invoice_id;
      source.status = "needs_review";
    }
    const invoice = await request(`/api/invoices/${encodeURIComponent(job.invoice_id)}`);
    showInvoice(invoice);
    notify("OCR complete. Please review the extracted details.");
  } catch (error) {
    ui.processing.hidden = true;
    ui.process.hidden = false;
    ui.process.disabled = false;
    ui.process.textContent = "Try OCR again";
    notify(error.message, true);
  }
}

function makeDraft() {
  return {
    vendor_name: ui.vendor.value.trim() || null,
    invoice_no: ui.invoiceNo.value.trim() || null,
    invoice_state: ui.invoiceState.value.trim() || null,
    items: state.items.map((item) => ({
      material_description: String(item.material_description || "").trim(),
      quantity: Number(item.quantity),
      price: Number(item.price),
    })),
  };
}

ui.fetch.addEventListener("click", fetchInvoices);
ui.process.addEventListener("click", runOcr);
ui.addItem.addEventListener("click", () => {
  state.items.push({ material_description: "", quantity: "", price: "" });
  renderItems();
  ui.items.querySelector("tr:last-child input")?.focus();
});

ui.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const invoice = [...state.invoices.values()].find(
    (item) => item.source_id === state.selectedId && item.status === "needs_review",
  );
  if (!invoice || !ui.form.reportValidity()) return;

  const draft = makeDraft();
  if (!draft.items.length || draft.items.some((item) =>
    !item.material_description || !Number.isFinite(item.quantity) ||
    !Number.isFinite(item.price)
  )) {
    notify("Add at least one complete line item before approval.", true);
    return;
  }

  ui.approve.disabled = true;
  ui.approve.textContent = "Saving…";
  try {
    const response = await request(
      `/api/invoices/${encodeURIComponent(invoice.id)}/approve`,
      { method: "POST", body: JSON.stringify({ draft }) },
    );
    invoice.status = "approved";
    invoice.draft = response.result;
    const source = state.sources.find((item) => item.id === state.selectedId);
    if (source) source.status = "approved";
    showInvoice(invoice);
    notify("Invoice approved. Review the JSON, then click Send JSON.");
  } catch (error) {
    notify(error.message, true);
    ui.approve.disabled = false;
  } finally {
    ui.approve.textContent = "Approve invoice";
  }
});

ui.copy.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(ui.resultJson.textContent);
    notify("JSON copied.");
  } catch {
    notify("Clipboard access is unavailable in this browser.", true);
  }
});

ui.send.addEventListener("click", async () => {
  const invoice = [...state.invoices.values()].find(
    (item) => item.source_id === state.selectedId && item.status === "approved",
  );
  if (!invoice) {
    notify("Approve the invoice before sending its JSON.", true);
    return;
  }

  ui.send.disabled = true;
  ui.send.textContent = "Sending...";
  try {
    const result = await request(
      `/api/invoices/${encodeURIComponent(invoice.id)}/result`,
    );
    ui.resultJson.textContent = JSON.stringify(result, null, 2);
    ui.resultJson.hidden = false;
    ui.copy.hidden = false;
    notify("Success! Your approved JSON has been sent back and is ready to copy.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    ui.send.disabled = false;
    ui.send.textContent = "Send JSON";
  }
});

async function initialize() {
  try {
    await request("/api/reset", { method: "POST" });
    state.invoices.clear();
    state.items = [];
    state.selectedId = null;
    state.sources = [];
    ui.invoicePanel.hidden = true;
    renderSources();
    ui.fetch.disabled = false;
  } catch (error) {
    notify(error.message, true);
  }
}

initialize();
