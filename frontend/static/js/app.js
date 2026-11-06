"use strict";

/* =========================================
   SAMPLE CHECK - FRONTEND APPLICATION
   Primary: Single-file sample inspection
   Secondary: Cross-file reconciliation
========================================= */

// Single-file inspection
const inspectionFile = document.getElementById("inspectionFile");
const inspectionFileName = document.getElementById("inspectionFileName");
const inspectBtn = document.getElementById("inspectBtn");
const inspectMessage = document.getElementById("inspectMessage");

// Built-in demo data
const loadDemoBtn = document.getElementById("loadDemoBtn");
const demoMessage = document.getElementById("demoMessage");
const inspectionResults = document.getElementById("inspectionResults");
const inspectionSummary = document.getElementById("inspectionSummary");
const inspectionBody = document.getElementById("inspectionBody");

// Reconciliation
const customerOrderFile = document.getElementById("customerOrderFile");
const labManifestFile = document.getElementById("labManifestFile");
const customerOrderName = document.getElementById("customerOrderName");
const labManifestName = document.getElementById("labManifestName");
const reconcileBtn = document.getElementById("reconcileBtn");
const reconcileMessage = document.getElementById("reconcileMessage");
const reconciliationResults = document.getElementById("reconciliationResults");
const reconciliationSummary = document.getElementById("reconciliationSummary");
const reconciliationBody = document.getElementById("reconciliationBody");

// Customer identity for optional reconciliation history
const customerCodeInput = document.getElementById("customerCode");
const customerNameInput = document.getElementById("customerName");
const loadCustomerHistoryBtn = document.getElementById("loadCustomerHistoryBtn");
const customerMessage = document.getElementById("customerMessage");

// AI
const aiAnalyzeBtn = document.getElementById("aiAnalyzeBtn");
const aiStatus = document.getElementById("aiStatus");
const aiResults = document.getElementById("aiResults");
const aiSummary = document.getElementById("aiSummary");
const aiActions = document.getElementById("aiActions");
const aiCustomerMessage = document.getElementById("aiCustomerMessage");
const aiLimitations = document.getElementById("aiLimitations");

// Staff review
const findingsBody = document.getElementById("findingsBody");

let isInspecting = false;
let isReconciling = false;
let isAnalyzing = false;
let isLoadingHistory = false;

let latestInspection = null;
let latestReconciliation = null;


/* =========================================
   SHARED HELPERS
========================================= */

function showMessage(element, message, type = "success") {
    if (!element) return;

    element.textContent = message;
    element.className = `message ${type}`;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);
}

function severityClass(value) {
    return String(value || "medium").toLowerCase();
}

async function getErrorMessage(response) {
    try {
        const data = await response.json();
        return data.detail || data.message || "Request failed.";
    } catch {
        return "Request failed. Please try again.";
    }
}

function formatDate(value) {
    if (!value) return "Date unavailable";

    const date = new Date(String(value).replace(" ", "T"));

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString();
}

function validateCsv(file) {
    if (!file) return "Please select a CSV file.";

    if (!file.name.toLowerCase().endsWith(".csv")) {
        return "Please select a CSV file.";
    }

    if (file.size === 0) {
        return "The selected file is empty.";
    }

    if (file.size > 2 * 1024 * 1024) {
        return "Maximum file size is 2 MB.";
    }

    return null;
}

function getSelectedCustomer() {
    return {
        code: customerCodeInput?.value.trim() || "",
        name: customerNameInput?.value.trim() || ""
    };
}

function validateCustomer() {
    const customer = getSelectedCustomer();

    if (!customer.code) {
        return "Please enter a customer code.";
    }

    if (!customer.name) {
        return "Please enter a customer or laboratory name.";
    }

    if (customer.code.length > 100) {
        return "Customer code must not exceed 100 characters.";
    }

    if (customer.name.length > 150) {
        return "Customer name must not exceed 150 characters.";
    }

    return null;
}

function isOldDemoValue(value) {
    const normalized = String(value || "").trim().toUpperCase();

    return [
        "ENTER CUSTOMER CODE",
        "ENTER LABORATORY NAME",
        "DEMO-CUSTOMER-01",
        "DEMO GENOMICS LABORATORY"
    ].includes(normalized);
}


/* =========================================
   SINGLE-FILE SAMPLE INSPECTION
========================================= */

inspectionFile?.addEventListener("change", () => {
    const file = inspectionFile.files[0];

    if (!file) {
        if (inspectionFileName) {
            inspectionFileName.textContent = "No file selected";
        }

        updateInspectButton();
        return;
    }

    const error = validateCsv(file);

    if (error) {
        inspectionFile.value = "";

        if (inspectionFileName) {
            inspectionFileName.textContent = "No file selected";
        }

        showMessage(inspectMessage, error, "error");
    } else {
        if (inspectionFileName) {
            inspectionFileName.textContent = file.name;
        }

        showMessage(inspectMessage, "CSV file selected. Ready for inspection.");
    }

    updateInspectButton();
});

function updateInspectButton() {
    if (!inspectBtn) return;

    inspectBtn.disabled = !(
        inspectionFile?.files?.[0] &&
        !isInspecting
    );
}

inspectBtn?.addEventListener("click", inspectSingleFile);


/* =========================================
   BUILT-IN DEMO DATA
   One handler only.
   Always requests the latest CSV without
   using a cached browser response.
========================================= */

loadDemoBtn?.addEventListener("click", loadDemoData);

async function loadDemoData() {
    if (isInspecting) return;

    if (!inspectionFile) {
        showMessage(
            demoMessage,
            "The sample inspection upload field was not found.",
            "error"
        );
        return;
    }

    if (!loadDemoBtn) {
        showMessage(
            demoMessage,
            "The Load Demo Data button was not found.",
            "error"
        );
        return;
    }

    loadDemoBtn.disabled = true;
    loadDemoBtn.textContent = "Loading demo data...";

    showMessage(demoMessage, "Preparing demo dataset...");

    try {
        const demoUrl =
            `/demo/sample_check_demo.csv?version=${Date.now()}`;

        const response = await fetch(demoUrl, {
            method: "GET",
            cache: "no-store",
            headers: {
                "Cache-Control": "no-cache"
            }
        });

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        const blob = await response.blob();

        if (!blob.size) {
            throw new Error("The demo CSV file is empty.");
        }

        const demoFile = new File(
            [blob],
            "sample_check_demo.csv",
            { type: "text/csv" }
        );

        const validationError = validateCsv(demoFile);

        if (validationError) {
            throw new Error(validationError);
        }

        const transfer = new DataTransfer();
        transfer.items.add(demoFile);

        inspectionFile.files = transfer.files;

        if (inspectionFileName) {
            inspectionFileName.textContent = demoFile.name;
        }

        updateInspectButton();

        showMessage(
            demoMessage,
            "Latest demo data loaded. Starting inspection..."
        );

        await inspectSingleFile();

    } catch (error) {
        console.error("Demo loading error:", error);

        showMessage(
            demoMessage,
            error.message || "Could not load the demo dataset.",
            "error"
        );

    } finally {
        if (loadDemoBtn) {
            loadDemoBtn.disabled = false;
            loadDemoBtn.textContent = "Load Demo Data →";
        }
    }
}


/* =========================================
   RUN SINGLE-FILE INSPECTION
========================================= */

async function inspectSingleFile() {
    if (isInspecting) return;

    const file = inspectionFile?.files?.[0];
    const error = validateCsv(file);

    if (error) {
        showMessage(inspectMessage, error, "error");
        return;
    }

    isInspecting = true;
    updateInspectButton();

    if (inspectBtn) {
        inspectBtn.textContent = "Inspecting samples...";
    }

    // A new inspection becomes the current primary result.
    latestInspection = null;
    latestReconciliation = null;

    if (aiResults) {
        aiResults.hidden = true;
    }

    if (inspectionResults) {
        inspectionResults.hidden = true;
    }

    if (reconciliationResults) {
        reconciliationResults.hidden = true;
    }

    const formData = new FormData();

    // The backend upload endpoint expects the uploaded CSV as "file".
    formData.append("file", file);

    try {
        const response = await fetch("/api/upload", {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        const data = await response.json();

        latestInspection = data.result || data;

        displayInspection(latestInspection);

        const sampleCount = Number(
            latestInspection.total_samples ??
            latestInspection.sample_count ??
            latestInspection.samples?.length ??
            0
        );

        const findingCount = Number(
            latestInspection.total_findings ??
            latestInspection.finding_count ??
            latestInspection.findings?.length ??
            0
        );

        showMessage(
            inspectMessage,
            `Inspection completed: ${sampleCount} samples checked and ${findingCount} exceptions identified.`
        );

        // Readiness is based on single-file inspection findings.
        updateReadiness(latestInspection.findings || []);

        // Refresh the primary staff-review dashboard.
        await refreshDashboard();

        showMessage(
            aiStatus,
            findingCount > 0
                ? "Inspection findings are ready for AI investigation."
                : "Inspection completed. No exceptions were detected."
        );

        // Bring the user to the inspection results.
        inspectionResults?.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });

    } catch (error) {
        console.error("Single-file inspection error:", error);
        showMessage(inspectMessage, error.message, "error");

    } finally {
        isInspecting = false;

        if (inspectBtn) {
            inspectBtn.textContent = "Inspect samples →";
        }

        updateInspectButton();
    }
}


function displayInspection(result) {
    if (!result) return;

    const findings = Array.isArray(result.findings)
        ? result.findings
        : [];

    const samples = Array.isArray(result.samples)
        ? result.samples
        : [];

    const sampleCount = Number(
        result.total_samples ??
        result.sample_count ??
        samples.length ??
        0
    );

    const findingCount = Number(
        result.total_findings ??
        result.finding_count ??
        findings.length
    );

    const cleanCount = Number(
        result.clean_samples ??
        result.clean_sample_count ??
        Math.max(0, sampleCount - findingCount)
    );

    if (inspectionSummary) {
        inspectionSummary.innerHTML = `
            <span class="result-chip">
                Samples inspected: ${sampleCount}
            </span>
            <span class="result-chip">
                Clean records: ${cleanCount}
            </span>
            <span class="result-chip">
                Exceptions: ${findingCount}
            </span>
        `;
    }

    if (inspectionBody) {
        if (!findings.length) {
            inspectionBody.innerHTML = `
                <tr>
                    <td colspan="5" class="empty">
                        No exceptions detected in this file.
                    </td>
                </tr>
            `;
        } else {
            inspectionBody.innerHTML = findings.map(finding => `
                <tr>
                    <td>${escapeHtml(finding.sample_id || "Missing ID")}</td>
                    <td>${escapeHtml(finding.issue_type || "Data issue")}</td>
                    <td>${escapeHtml(finding.description || "")}</td>
                    <td>
                        <span class="severity ${severityClass(finding.severity)}">
                            ${escapeHtml(finding.severity || "Medium")}
                        </span>
                    </td>
                    <td>${Number(finding.row_number || finding.row || finding.line_number || 0) || "—"}</td>
                </tr>
            `).join("");
        }
    }

    if (inspectionResults) {
        inspectionResults.hidden = false;
    }
}


/* =========================================
   CUSTOMER IDENTITY
   Used by optional cross-file reconciliation
========================================= */

function customerIdentityChanged() {
    latestReconciliation = null;

    if (aiResults) {
        aiResults.hidden = true;
    }

    const container = document.getElementById("errorIntelligence");

    if (container) {
        container.innerHTML = `
            <p class="muted-text">
                Customer details changed. Load this customer's history
                to view the correct submission records.
            </p>
        `;
    }

    showMessage(
        customerMessage,
        "Customer details changed. Load the selected customer's history.",
        "success"
    );
}

customerCodeInput?.addEventListener("input", customerIdentityChanged);
customerNameInput?.addEventListener("input", customerIdentityChanged);

loadCustomerHistoryBtn?.addEventListener("click", async () => {
    const error = validateCustomer();

    if (error) {
        showMessage(customerMessage, error, "error");
        return;
    }

    await loadErrorIntelligence();
});


/* =========================================
   OPTIONAL RECONCILIATION FILE SELECTION
========================================= */

function updateReconcileButton() {
    if (!reconcileBtn) return;

    reconcileBtn.disabled = !(
        customerOrderFile?.files?.[0] &&
        labManifestFile?.files?.[0] &&
        !isReconciling
    );
}

customerOrderFile?.addEventListener("change", () => {
    const file = customerOrderFile.files[0];

    if (!file) {
        if (customerOrderName) {
            customerOrderName.textContent = "No file selected";
        }

        updateReconcileButton();
        return;
    }

    const error = validateCsv(file);

    if (error) {
        customerOrderFile.value = "";

        if (customerOrderName) {
            customerOrderName.textContent = "No file selected";
        }

        showMessage(reconcileMessage, error, "error");
    } else {
        if (customerOrderName) {
            customerOrderName.textContent = file.name;
        }

        showMessage(reconcileMessage, "Customer order selected.");
    }

    updateReconcileButton();
});

labManifestFile?.addEventListener("change", () => {
    const file = labManifestFile.files[0];

    if (!file) {
        if (labManifestName) {
            labManifestName.textContent = "No file selected";
        }

        updateReconcileButton();
        return;
    }

    const error = validateCsv(file);

    if (error) {
        labManifestFile.value = "";

        if (labManifestName) {
            labManifestName.textContent = "No file selected";
        }

        showMessage(reconcileMessage, error, "error");
    } else {
        if (labManifestName) {
            labManifestName.textContent = file.name;
        }

        showMessage(reconcileMessage, "Laboratory manifest selected.");
    }

    updateReconcileButton();
});


/* =========================================
   CROSS-FILE RECONCILIATION
   Secondary workflow
========================================= */

reconcileBtn?.addEventListener("click", reconcileFiles);

async function reconcileFiles() {
    if (isReconciling) return;

    const order = customerOrderFile?.files?.[0];
    const manifest = labManifestFile?.files?.[0];

    if (!order || !manifest) {
        showMessage(
            reconcileMessage,
            "Please select both CSV files.",
            "error"
        );
        return;
    }

    const customerError = validateCustomer();

    if (customerError) {
        showMessage(customerMessage, customerError, "error");
        return;
    }

    const customer = getSelectedCustomer();

    isReconciling = true;
    updateReconcileButton();

    reconcileBtn.textContent = "Comparing files...";

    const formData = new FormData();

    formData.append("customer_order", order);
    formData.append("lab_manifest", manifest);
    formData.append("customer_code", customer.code);
    formData.append("customer_name", customer.name);

    try {
        const response = await fetch("/api/reconcile", {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        const data = await response.json();

        latestReconciliation = data.result || null;

        displayReconciliation(latestReconciliation);

        showMessage(
            reconcileMessage,
            `Reconciliation completed: ${Number(latestReconciliation?.exception_count || 0)} exceptions found.`
        );

        showMessage(
            customerMessage,
            `Submission saved under ${data.customer_code || customer.code}.`
        );

        if (reconciliationResults) {
            reconciliationResults.hidden = false;
        }

        // Do not overwrite the primary single-file readiness score.
        showMessage(
            aiStatus,
            "Reconciliation results are ready. AI can investigate these results when selected."
        );

        if (data.repeat_error_intelligence) {
            displayErrorIntelligence(data.repeat_error_intelligence);
        } else {
            await loadErrorIntelligence();
        }

    } catch (error) {
        console.error("Reconciliation error:", error);
        showMessage(reconcileMessage, error.message, "error");

    } finally {
        isReconciling = false;

        if (reconcileBtn) {
            reconcileBtn.textContent = "Run optional reconciliation →";
        }

        updateReconcileButton();
    }
}


function displayReconciliation(result) {
    if (!reconciliationSummary || !reconciliationBody || !result) return;

    reconciliationSummary.innerHTML = `
        <span class="result-chip">
            Customer orders: ${Number(result.customer_order_count || 0)}
        </span>
        <span class="result-chip">
            Lab records: ${Number(result.lab_manifest_count || 0)}
        </span>
        <span class="result-chip">
            Matched: ${Number(result.matched_sample_count || 0)}
        </span>
        <span class="result-chip">
            Clean matches: ${Number(result.clean_matched_count || 0)}
        </span>
        <span class="result-chip">
            Exceptions: ${Number(result.exception_count || 0)}
        </span>
    `;

    const findings = Array.isArray(result.findings)
        ? result.findings
        : [];

    if (!findings.length) {
        reconciliationBody.innerHTML = `
            <tr>
                <td colspan="5" class="empty">
                    No reconciliation exceptions detected.
                </td>
            </tr>
        `;
        return;
    }

    reconciliationBody.innerHTML = findings.map(finding => {
        const evidence = (finding.evidence || [])
            .map(item => {
                const field = item.field
                    ? ` · ${escapeHtml(item.field)}: ${escapeHtml(item.value)}`
                    : "";

                return `${escapeHtml(item.file)}, row ${Number(item.row)}${field}`;
            })
            .join("<br>");

        const repeatLabel = finding.is_repeat
            ? `
                <span class="repeat-label">Recurring error</span>
            `
            : "";

        return `
            <tr>
                <td>${escapeHtml(finding.sample_id || "—")}</td>
                <td>${escapeHtml(finding.issue_type || "Issue")}${repeatLabel}</td>
                <td>${escapeHtml(finding.description || "")}</td>
                <td>
                    <span class="severity ${severityClass(finding.severity)}">
                        ${escapeHtml(finding.severity || "Medium")}
                    </span>
                </td>
                <td>${evidence || "No evidence details"}</td>
            </tr>
        `;
    }).join("");
}


/* =========================================
   REPEAT ERROR INTELLIGENCE
========================================= */

function displayErrorIntelligence(data) {
    const container = document.getElementById("errorIntelligence");

    if (!container) return;

    if (!data) {
        container.innerHTML = `
            <p class="muted-text">
                No historical submission information is available yet.
                Run optional reconciliation and load a customer history
                to build these insights.
            </p>
        `;
        return;
    }

    const recurringErrors = Array.isArray(data.recurring_errors)
        ? data.recurring_errors
        : [];

    const checklist = Array.isArray(data.checklist)
        ? data.checklist
        : [];

    const history = Array.isArray(data.history)
        ? data.history
        : [];

    const totalSubmissions = Number(data.submission_count || 0);

    const totalOccurrences = recurringErrors.reduce(
        (sum, item) => sum + Number(item.total_occurrences || 0),
        0
    );

    const recurringHtml = recurringErrors.length
        ? recurringErrors.map(item => `
            <div class="intelligence-item">
                <div class="intelligence-item-heading">
                    <strong>${escapeHtml(item.issue_type)}</strong>
                    <span class="repeat-label">Recurring</span>
                </div>
                <div class="intelligence-meta">
                    <span>${Number(item.submission_count || 0)} submissions affected</span>
                    <span>${Number(item.total_occurrences || 0)} total occurrences</span>
                </div>
            </div>
        `).join("")
        : `
            <p class="muted-text">
                No recurring errors have been identified yet.
                More submission history will improve these insights.
            </p>
        `;

    const checklistHtml = checklist.length
        ? checklist.map((item, index) => `
            <div class="checklist-item">
                <span class="checklist-number">${index + 1}</span>
                <div>
                    <strong>${escapeHtml(item.issue_type)}</strong>
                    <p>${escapeHtml(item.instruction)}</p>
                    <span class="muted-text">
                        Previously reported in
                        ${Number(item.previous_submissions || 0)}
                        submissions
                    </span>
                </div>
            </div>
        `).join("")
        : `
            <p class="muted-text">
                A prevention checklist will appear when recurring
                patterns are identified.
            </p>
        `;

    const historyHtml = history.length
        ? `
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Submission</th>
                            <th>Samples</th>
                            <th>Errors</th>
                            <th>Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${history.map(item => `
                            <tr>
                                <td>#${Number(item.id)}</td>
                                <td>${Number(item.total_samples || 0)}</td>
                                <td>${Number(item.error_count || 0)}</td>
                                <td>${escapeHtml(formatDate(item.submitted_at))}</td>
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            </div>
        `
        : `
            <p class="muted-text">
                No submission history is available for this customer.
            </p>
        `;

    container.innerHTML = `
        <div class="intelligence-header">
            <div>
                <h3>${escapeHtml(data.customer_name || "Customer")}</h3>
                <p>Customer code: ${escapeHtml(data.customer_code || "")}</p>
            </div>
            <span class="history-label">Historical analysis</span>
        </div>

        <div class="intelligence-stats">
            <div class="intelligence-stat">
                <span>Total submissions</span>
                <strong>${totalSubmissions}</strong>
            </div>
            <div class="intelligence-stat">
                <span>Recurring error types</span>
                <strong>${recurringErrors.length}</strong>
            </div>
            <div class="intelligence-stat">
                <span>Recurring occurrences</span>
                <strong>${totalOccurrences}</strong>
            </div>
        </div>

        <section class="intelligence-section">
            <h3>Repeated error patterns</h3>
            ${recurringHtml}
        </section>

        <section class="intelligence-section checklist-panel">
            <h3>Personalized prevention checklist</h3>
            <p>Review these items before accepting the customer's next batch.</p>
            ${checklistHtml}
        </section>

        <section class="intelligence-section">
            <h3>Submission history</h3>
            ${historyHtml}
        </section>

        <p class="muted-text">
            These insights are based on recorded submission history.
            They support administrative review and do not replace
            laboratory quality-control procedures.
        </p>
    `;
}


async function loadErrorIntelligence() {
    const container = document.getElementById("errorIntelligence");
    const customer = getSelectedCustomer();

    if (!customer.code || !customer.name) {
        showMessage(
            customerMessage,
            "Enter both customer details before loading history.",
            "error"
        );
        return;
    }

    if (isLoadingHistory) return;

    isLoadingHistory = true;

    if (loadCustomerHistoryBtn) {
        loadCustomerHistoryBtn.disabled = true;
        loadCustomerHistoryBtn.textContent = "Loading...";
    }

    if (container) {
        container.innerHTML = `
            <p class="muted-text">
                Loading history for ${escapeHtml(customer.code)}...
            </p>
        `;
    }

    try {
        const response = await fetch(
            `/api/error-intelligence?customer_code=${encodeURIComponent(customer.code)}`
        );

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        const data = await response.json();
        const currentCustomer = getSelectedCustomer();

        if (
            currentCustomer.code.toUpperCase() !== customer.code.toUpperCase() ||
            currentCustomer.name !== customer.name
        ) {
            return;
        }

        displayErrorIntelligence(data);

        showMessage(
            customerMessage,
            `Loaded history for ${data.customer_name || customer.name}.`
        );

    } catch (error) {
        console.error("Error Intelligence loading error:", error);

        if (container) {
            container.innerHTML = `
                <p class="message error">
                    Could not load submission history:
                    ${escapeHtml(error.message)}
                </p>
            `;
        }

        showMessage(customerMessage, error.message, "error");

    } finally {
        isLoadingHistory = false;

        if (loadCustomerHistoryBtn) {
            loadCustomerHistoryBtn.disabled = false;
            loadCustomerHistoryBtn.textContent = "Load customer history";
        }
    }
}


/* =========================================
   VULTR AI INVESTIGATION
========================================= */

aiAnalyzeBtn?.addEventListener("click", analyzeWithAI);

function displayAIReport(data) {
    if (!data) return;

    const analysis = data.analysis || {};

    if (aiSummary) {
        aiSummary.textContent =
            analysis.summary || "No summary was returned.";
    }

    if (aiActions) {
        aiActions.innerHTML = "";

        const actions = Array.isArray(analysis.priority_actions)
            ? analysis.priority_actions
            : [];

        if (actions.length) {
            actions.forEach(action => {
                const li = document.createElement("li");

                if (typeof action === "string") {
                    li.textContent = action;
                } else {
                    const sample = action.sample_id
                        ? `${action.sample_id}: `
                        : "";

                    const issue = action.issue
                        ? `${action.issue}. `
                        : "";

                    const explanation = action.explanation || "";

                    const recommendation = action.recommended_action
                        ? ` Recommended action: ${action.recommended_action}`
                        : "";

                    const priority = action.priority
                        ? ` Priority: ${action.priority}.`
                        : "";

                    li.textContent =
                        sample + issue + explanation +
                        recommendation + priority;
                }

                aiActions.appendChild(li);
            });
        } else {
            const li = document.createElement("li");
            li.textContent = "No priority actions were returned.";
            aiActions.appendChild(li);
        }
    }

    if (aiCustomerMessage) {
        aiCustomerMessage.textContent =
            analysis.customer_message ||
            "No customer message was generated.";
    }

    if (aiLimitations) {
        aiLimitations.textContent = analysis.limitations || "";
    }

    if (aiResults) {
        aiResults.hidden = false;
    }

    const clarificationContent =
        document.getElementById("clarificationContent");

    if (clarificationContent) {
        clarificationContent.textContent =
            analysis.customer_message ||
            "No clarification draft generated yet.";
    }
}


async function analyzeWithAI() {
    if (isAnalyzing) return;

    isAnalyzing = true;

    if (aiAnalyzeBtn) {
        aiAnalyzeBtn.disabled = true;
        aiAnalyzeBtn.textContent = "Investigating...";
    }

    const hasReconciliation = latestReconciliation !== null;

    showMessage(
        aiStatus,
        hasReconciliation
            ? "Sending reconciliation findings to Vultr AI..."
            : "Sending the latest sample inspection findings to Vultr AI..."
    );

    try {
        const requestOptions = {
            method: "POST"
        };

        // If the user has run an optional reconciliation, investigate
        // those findings. Otherwise the backend uses the latest
        // single-file inspection findings from this visitor's session.
        if (hasReconciliation) {
            requestOptions.headers = {
                "Content-Type": "application/json"
            };

            requestOptions.body = JSON.stringify({
                source: "reconciliation",
                findings: latestReconciliation.findings || []
            });
        }

        const response = await fetch("/api/ai/analyze", requestOptions);

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        const data = await response.json();

        displayAIReport(data);

        const sourceLabel =
            data.analysis_source === "reconciliation"
                ? "reconciliation findings"
                : "sample inspection findings";

        showMessage(
            aiStatus,
            `AI investigation completed using ${data.model || "Vultr AI"} (${data.analyzed_findings ?? "—"} findings from ${sourceLabel}).`
        );

    } catch (error) {
        console.error("AI investigation error:", error);
        showMessage(aiStatus, error.message, "error");

    } finally {
        isAnalyzing = false;

        if (aiAnalyzeBtn) {
            aiAnalyzeBtn.disabled = false;
            aiAnalyzeBtn.textContent = "✦ Investigate with AI";
        }
    }
}


/* =========================================
   BATCH READINESS
   Based on single-file inspection findings
========================================= */

function updateReadiness(findings = []) {
    const scoreElement = document.getElementById("readinessScore");
    const explanationElement =
        document.getElementById("readinessExplanation");
    const barElement = document.getElementById("readinessBar");

    if (!scoreElement || !explanationElement || !barElement) return;

    let deduction = 0;

    findings.forEach(finding => {
        const severity = String(finding.severity || "medium").toLowerCase();

        if (severity === "high") {
            deduction += 20;
        } else if (severity === "medium") {
            deduction += 10;
        } else {
            deduction += 5;
        }
    });

    const score = Math.max(0, 100 - deduction);

    scoreElement.textContent = `${score}/100`;
    barElement.style.width = `${score}%`;

    explanationElement.textContent =
        `${findings.length} inspection exceptions identified. ` +
        "Each high-severity issue deducts 20 points, each medium issue 10 points, " +
        "and each low-severity issue 5 points. This illustrative administrative " +
        "score is not a clinical or laboratory QC approval.";
}


/* =========================================
   STAFF REVIEW DASHBOARD
   Reads single-file inspection findings
========================================= */

async function refreshDashboard() {
    try {
        const [statsResponse, findingsResponse] = await Promise.all([
            fetch("/api/stats"),
            fetch("/api/findings")
        ]);

        if (!statsResponse.ok || !findingsResponse.ok) {
            throw new Error("Dashboard refresh failed.");
        }

        const stats = await statsResponse.json();
        const data = await findingsResponse.json();

        const totalSamples = document.getElementById("totalSamples");
        const totalFindings = document.getElementById("totalFindings");
        const openFindings = document.getElementById("openFindings");
        const resolvedFindings = document.getElementById("resolvedFindings");

        if (totalSamples) {
            totalSamples.textContent = stats.total_samples ?? 0;
        }

        if (totalFindings) {
            totalFindings.textContent = stats.total_findings ?? 0;
        }

        if (openFindings) {
            openFindings.textContent = stats.open_findings ?? 0;
        }

        if (resolvedFindings) {
            resolvedFindings.textContent = stats.resolved_findings ?? 0;
        }

        if (!findingsBody) return;

        if (!data.findings || !data.findings.length) {
            findingsBody.innerHTML = `
                <tr>
                    <td colspan="6" class="empty">
                        No exceptions detected in the latest inspection.
                    </td>
                </tr>
            `;
            return;
        }

        findingsBody.innerHTML = data.findings.map(finding => `
            <tr>
                <td>${escapeHtml(finding.sample_id || "Missing ID")}</td>
                <td>${escapeHtml(finding.issue_type || "Data issue")}</td>
                <td>${escapeHtml(finding.description || "")}</td>
                <td>
                    <span class="severity ${severityClass(finding.severity)}">
                        ${escapeHtml(finding.severity || "Medium")}
                    </span>
                </td>
                <td>${escapeHtml(finding.status || "Open")}</td>
                <td>
                    ${finding.status === "Open"
                        ? `<button class="resolve-btn"
                            data-finding-id="${Number(finding.id)}">
                            Resolve
                           </button>`
                        : '<span class="done">Resolved</span>'}
                </td>
            </tr>
        `).join("");

    } catch (error) {
        console.error("Dashboard refresh error:", error);
    }
}


/* =========================================
   RESOLVE STAFF REVIEW EXCEPTION
========================================= */

findingsBody?.addEventListener("click", async event => {
    const button = event.target.closest(".resolve-btn");

    if (!button) return;

    const findingId = Number(button.dataset.findingId);

    if (!Number.isInteger(findingId) || findingId <= 0) return;

    button.disabled = true;
    button.textContent = "Updating...";

    try {
        const response = await fetch(
            `/api/findings/${findingId}/resolve`,
            { method: "PATCH" }
        );

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        await refreshDashboard();

    } catch (error) {
        alert(error.message);
        button.disabled = false;
        button.textContent = "Resolve";
    }
});


/* =========================================
   RESTORE OPTIONAL RECONCILIATION WORKSPACE
========================================= */

async function restoreLatestReconciliation() {
    try {
        const response = await fetch("/api/latest-reconciliation");

        if (!response.ok) {
            throw new Error(await getErrorMessage(response));
        }

        const data = await response.json();

        if (!data.saved) {
            latestReconciliation = null;
            return;
        }

        if (data.result) {
            latestReconciliation = data.result;

            displayReconciliation(data.result);

            if (reconciliationResults) {
                reconciliationResults.hidden = false;
            }

            showMessage(
                reconcileMessage,
                "Your previous optional reconciliation has been restored."
            );
        }

        const savedCode = String(data.customer_code || "").trim();
        const savedName = String(data.customer_name || "").trim();

        const isOldDemoCustomer =
            isOldDemoValue(savedCode) ||
            isOldDemoValue(savedName);

        if (!isOldDemoCustomer) {
            if (customerCodeInput && savedCode) {
                customerCodeInput.value = savedCode;
            }

            if (customerNameInput && savedName) {
                customerNameInput.value = savedName;
            }
        }

        if (data.ai_report) {
            displayAIReport(data.ai_report);

            showMessage(
                aiStatus,
                "Your previous AI investigation has been restored."
            );
        }

        if (!isOldDemoCustomer && savedCode && savedName) {
            await loadErrorIntelligence();
        }

    } catch (error) {
        console.error("Optional reconciliation restoration error:", error);
    }
}


/* =========================================
   INITIALIZATION
========================================= */

updateInspectButton();
updateReconcileButton();

displayErrorIntelligence(null);

// Load only the latest single-file inspection dashboard.
refreshDashboard();

// Do not automatically restore old reconciliation results.
// Previous reconciliation data remains safely stored in the database.
latestReconciliation = null;