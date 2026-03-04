/* ============================================================
   PDF Print Readiness Checker — dropzone UX only.
   All networking is handled by HTMX (see index.html).
   ============================================================ */

(function () {
    "use strict";

    // ── DOM references ──────────────────────────────────────────
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");
    const form = document.getElementById("uploadForm");

    // ── Dropzone click / keyboard ───────────────────────────────
    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInput.click();
        }
    });

    // ── Drag-and-drop ───────────────────────────────────────────
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("drag-over");
    });

    ["dragleave", "dragend"].forEach((evt) => {
        dropzone.addEventListener(evt, () => dropzone.classList.remove("drag-over"));
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("drag-over");
        const file = e.dataTransfer.files[0];
        if (!file) return;
        setFileAndSubmit(file);
    });

    // ── File-input change ───────────────────────────────────────
    fileInput.addEventListener("change", () => {
        if (fileInput.files[0]) form.requestSubmit();
    });

    // ── Helpers ─────────────────────────────────────────────────
    function setFileAndSubmit(file) {
        // Assign the dragged file to the hidden input so HTMX picks it up
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        form.requestSubmit();
    }

    // ── After HTMX swaps in the results, hide dropzone ──
    document.addEventListener("htmx:afterSwap", (e) => {
        if (e.detail.target.id === "results-area") {
            const dropzone = document.getElementById("dropzone");
            if (dropzone) dropzone.hidden = true;
            e.detail.target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    });
})();

/* ============================================================
   Section summarization — called by hx-on:htmx:after-swap
   on each .check-list after its group results load.
   ============================================================ */
function summarizeSection(checkList) {
    const section = checkList.closest(".check-section");
    const badge = section.querySelector(".section-status-badge");
    const items = Array.from(checkList.querySelectorAll(".check-item:not(.loading)"));

    if (!items.length) return;

    const issues = items.filter((i) => i.dataset.status !== "pass");
    const passes = items.filter((i) => i.dataset.status === "pass");
    const errors = issues.filter((i) => i.dataset.status === "error" || i.dataset.status === "fail");
    const warns = issues.filter((i) => i.dataset.status === "warning");

    // ── Update the header status badge ───────────────────────
    if (issues.length === 0) {
        badge.textContent = `✓ All passed`;
        badge.className = "section-status-badge sbadge-pass";
    } else if (errors.length > 0) {
        badge.textContent = `✗ ${errors.length} error${errors.length > 1 ? "s" : ""}`;
        badge.className = "section-status-badge sbadge-fail";
    } else {
        const wc = warns.length;
        const ic = issues.filter((i) => i.dataset.status === "info").length;
        if (wc > 0) {
            badge.textContent = `⚠ ${wc} warning${wc > 1 ? "s" : ""}`;
            badge.className = "section-status-badge sbadge-warn";
        } else {
            badge.textContent = `ℹ ${ic} note${ic > 1 ? "s" : ""}`;
            badge.className = "section-status-badge sbadge-info";
        }
    }

    // ── Restructure the list ──────────────────────────────────
    if (issues.length === 0) {
        // All passed — show summary row with items in a closed twirl-down
        const details = document.createElement("details");
        details.className = "passed-items-details all-pass-details";
        const summary = document.createElement("summary");
        summary.className = "passed-items-summary all-pass-summary";
        summary.innerHTML = `<span class="all-pass-icon">✓</span> All ${passes.length} check${passes.length > 1 ? "s" : ""} passed`;
        details.appendChild(summary);
        passes.forEach((p) => details.appendChild(p));
        checkList.innerHTML = "";
        checkList.appendChild(details);
        section.classList.add("all-pass", "collapsed");
        section.querySelector(".check-section-header").setAttribute("aria-expanded", "false");
    } else {
        // Issues visible; bundle any passing items into a disclosure
        if (passes.length > 0) {
            const details = document.createElement("details");
            details.className = "passed-items-details";
            const summary = document.createElement("summary");
            summary.className = "passed-items-summary";
            summary.textContent = `${passes.length} passed check${passes.length > 1 ? "s" : ""}`;
            details.appendChild(summary);
            passes.forEach((p) => details.appendChild(p));
            checkList.appendChild(details);
        }
        section.classList.add("has-issues");
    }

    section.classList.add("loaded");
}

/* Toggle a section open / closed when its header is clicked */
function toggleSection(headerBtn) {
    const section = headerBtn.closest(".check-section");
    const expanded = headerBtn.getAttribute("aria-expanded") === "true";
    headerBtn.setAttribute("aria-expanded", String(!expanded));
    section.classList.toggle("collapsed", expanded);
}

/* ============================================================
   Fix Panel — toggle open/closed
   ============================================================ */

function toggleFixPanel(btn) {
    const formArea = document.getElementById("fp-form-area");
    const open = btn.getAttribute("aria-expanded") === "true";
    if (open) {
        btn.setAttribute("aria-expanded", "false");
        formArea.hidden = true;
        btn.querySelector(".fp-toggle-label").textContent = "Create Fixed PDF";
    } else {
        btn.setAttribute("aria-expanded", "true");
        formArea.hidden = false;
        btn.querySelector(".fp-toggle-label").textContent = "Hide options";
        // Trigger an initial preview render and summary update
        fpUpdatePreview();
        formArea.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
}

/* ============================================================
   Fix Panel — live preview + page navigation
   ============================================================ */

let fpCurrentPage = 1;

function fpOnTrimChanged() {
    fpUpdatePreview();
    document.body.dispatchEvent(new CustomEvent("fp-trim-changed"));
}

function fpGoToPage(delta) {
    const panel = document.getElementById("fix-panel");
    if (!panel) return;
    const total = parseInt(panel.dataset.pageCount, 10) || 1;
    fpCurrentPage = Math.max(1, Math.min(total, fpCurrentPage + delta));
    document.getElementById("fp-page-cur").textContent = fpCurrentPage;
    document.getElementById("fp-prev-btn").disabled = fpCurrentPage === 1;
    document.getElementById("fp-next-btn").disabled = fpCurrentPage === total;
    fpUpdatePreview();
}

/** Open the full-size preview zoom dialog. */
function fpOpenZoom() {
    const dialog = document.getElementById("fp-zoom-dialog");
    const panel = document.getElementById("fix-panel");
    const srcImg = document.getElementById("fp-preview-img");
    const zoomImg = document.getElementById("fp-zoom-img");
    if (!dialog || !panel || !srcImg || !zoomImg) return;

    const total = parseInt(panel.dataset.pageCount, 10) || 1;
    document.getElementById("fp-zoom-cur").textContent = fpCurrentPage;
    document.getElementById("fp-zoom-total").textContent = total;
    document.getElementById("fp-zoom-prev").disabled = fpCurrentPage === 1;
    document.getElementById("fp-zoom-next").disabled = fpCurrentPage === total;

    // Derive zoom src from current preview, bumping scale to 4.0
    zoomImg.src = srcImg.src.replace(/scale=[0-9.]+/, "scale=4.0");

    if (!dialog.dataset.closeReady) {
        dialog.dataset.closeReady = "1";
        dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
    }
    dialog.showModal();
}

/** Navigate pages inside the zoom modal (also syncs main panel). */
function fpZoomPage(delta) {
    const panel = document.getElementById("fix-panel");
    if (!panel) return;
    const total = parseInt(panel.dataset.pageCount, 10) || 1;
    fpCurrentPage = Math.max(1, Math.min(total, fpCurrentPage + delta));
    // Sync main panel counters/buttons
    document.getElementById("fp-page-cur").textContent = fpCurrentPage;
    document.getElementById("fp-prev-btn").disabled = fpCurrentPage === 1;
    document.getElementById("fp-next-btn").disabled = fpCurrentPage === total;
    // Sync zoom counters/buttons
    document.getElementById("fp-zoom-cur").textContent = fpCurrentPage;
    document.getElementById("fp-zoom-prev").disabled = fpCurrentPage === 1;
    document.getElementById("fp-zoom-next").disabled = fpCurrentPage === total;
    fpUpdatePreview();
}

/**
 * Rebuild the preview image src and geometry summary whenever trim or page changes.
 */
function fpUpdatePreview() {
    const panel = document.getElementById("fix-panel");
    if (!panel) return;

    const jobId = panel.dataset.jobId;
    const select = document.getElementById("fp-preset-trim");
    const applyTrim = document.getElementById("fp-apply-trim");
    const useTrimFix = !applyTrim || applyTrim.checked;
    const img = document.getElementById("fp-preview-img");
    const dlBtn = document.getElementById("fp-dl-btn");
    const trimVal = document.getElementById("fp-geo-trim-val");
    const bleedVal = document.getElementById("fp-geo-bleed-val");
    if (!img) return;

    // Trim/Bleed fix disabled OR no size selected — plain preview
    if (!useTrimFix || !select.value) {
        if (dlBtn) dlBtn.disabled = useTrimFix && !select.value;
        if (trimVal) trimVal.textContent = "—";
        if (bleedVal) bleedVal.textContent = useTrimFix ? "—" : "Fix disabled";
        const plainUrl = `/check/${jobId}/preview/${fpCurrentPage}?scale=2.0`;
        img.src = plainUrl;
        const zd = document.getElementById("fp-zoom-dialog");
        const zi = document.getElementById("fp-zoom-img");
        if (zd && zd.open && zi) zi.src = plainUrl.replace("scale=2.0", "scale=4.0");
        return;
    }

    const [sw, sh] = select.value.split(",").map(Number);

    // Auto-orient: preset sizes are listed in landscape order (e.g. "3.5,2.0").
    // If the canvas is portrait (h > w) but the preset is landscape, swap so
    // the trim matches the actual canvas orientation.
    const canvasWPt = parseFloat(panel.dataset.canvasWPt) || 0;
    const canvasHPt = parseFloat(panel.dataset.canvasHPt) || 0;
    const canvasIsPortrait = canvasHPt > canvasWPt + 1; // +1 pt tolerance for square
    const presetIsPortrait = sh > sw + 0.001;
    let wIn = sw > 0 ? sw : 0;
    let hIn = sh > 0 ? sh : 0;
    if (canvasWPt > 0 && canvasIsPortrait !== presetIsPortrait) {
        [wIn, hIn] = [hIn, wIn];
    }

    const trimWPt = wIn * 72;
    const trimHPt = hIn * 72;
    const requestedBleedPt = 9.0;

    // Compute actual bleed: capped by the available margin on each axis so we
    // never claim more bleed than the canvas can provide.
    const marginX = canvasWPt > 0 ? (canvasWPt - trimWPt) / 2 : requestedBleedPt;
    const marginY = canvasHPt > 0 ? (canvasHPt - trimHPt) / 2 : requestedBleedPt;
    const actualBleedPt = Math.min(requestedBleedPt, Math.max(0, marginX), Math.max(0, marginY));

    if (dlBtn) dlBtn.disabled = false;

    // Debounce the preview image update
    if (fpUpdatePreview._timer) clearTimeout(fpUpdatePreview._timer);
    fpUpdatePreview._timer = setTimeout(() => {
        const url = `/check/${jobId}/preview/${fpCurrentPage}?scale=2.0` +
            `&ov_trim_w_pt=${trimWPt.toFixed(2)}` +
            `&ov_trim_h_pt=${trimHPt.toFixed(2)}` +
            `&ov_bleed_pt=${actualBleedPt.toFixed(3)}`;
        img.classList.add("loading");
        img.onload = () => img.classList.remove("loading");
        img.onerror = () => img.classList.remove("loading");
        img.src = url;
        // Keep zoom modal in sync
        const zoomDialog = document.getElementById("fp-zoom-dialog");
        const zoomImg = document.getElementById("fp-zoom-img");
        if (zoomDialog && zoomDialog.open && zoomImg) {
            zoomImg.src = url.replace("scale=2.0", "scale=4.0");
        }
    }, 220);

    // Update geometry summary
    if (trimVal) {
        trimVal.textContent = `${wIn.toFixed(3)}" × ${hIn.toFixed(3)}" — centered`;
    }
    if (bleedVal) {
        if (actualBleedPt > 0.5) {
            const bleedIn = (actualBleedPt / 72).toFixed(3);
            bleedVal.textContent = `trim + ${bleedIn}" per side`;
        } else {
            bleedVal.textContent = "No bleed margin — canvas = trim size";
        }
    }
}

/* ============================================================
   Upload Modal — trim selection & live preview
   ============================================================ */

/**
 * Update the modal preview image whenever trim size changes.
 * Debounced 200 ms to avoid hammering the server while the user picks.
 */
function umUpdatePreview(jobId) {
    const select = document.getElementById("um-preset-trim");
    if (!select) return;

    const [sw, sh] = select.value.split(",").map(Number);

    // Auto-orient: same logic as fpUpdatePreview — swap trim to match canvas.
    const dialog = document.getElementById("upload-modal");
    const canvasWPt = dialog ? (parseFloat(dialog.dataset.canvasWPt) || 0) : 0;
    const canvasHPt = dialog ? (parseFloat(dialog.dataset.canvasHPt) || 0) : 0;
    const canvasIsPortrait = canvasHPt > canvasWPt + 1;
    const presetIsPortrait = sh > sw + 0.001;
    let wIn = sw > 0 ? sw : 0;
    let hIn = sh > 0 ? sh : 0;
    if (canvasWPt > 0 && canvasIsPortrait !== presetIsPortrait) {
        [wIn, hIn] = [hIn, wIn];
    }
    const trimWPt = wIn * 72;
    const trimHPt = hIn * 72;
    const marginX = canvasWPt > 0 ? (canvasWPt - trimWPt) / 2 : 9;
    const marginY = canvasHPt > 0 ? (canvasHPt - trimHPt) / 2 : 9;
    const bleedPt = Math.min(9.0, Math.max(0, marginX), Math.max(0, marginY));

    const img = document.getElementById("um-preview-img");
    if (!img) return;

    if (umUpdatePreview._timer) clearTimeout(umUpdatePreview._timer);
    umUpdatePreview._timer = setTimeout(() => {
        img.classList.add("loading");
        img.onload = () => img.classList.remove("loading");
        img.onerror = () => img.classList.remove("loading");
        img.src =
            `/check/${jobId}/preview/1?scale=1.6` +
            `&ov_trim_w_pt=${trimWPt.toFixed(2)}` +
            `&ov_trim_h_pt=${trimHPt.toFixed(2)}` +
            `&ov_bleed_pt=${bleedPt.toFixed(3)}`;
    }, 200);
}

/* ============================================================
   Fix Panel — inline preflight check rows
   ============================================================ */

/**
 * Called by HTMX after each hidden check-list loads.
 * Computes pass/fail status and updates the row badge + enables Details btn.
 */
function fpSummarizeRow(checkList, group) {
    const items = Array.from(checkList.querySelectorAll(".check-item:not(.loading)"));
    const badge = document.getElementById("fp-badge-" + group);
    const btn = document.getElementById("fp-details-btn-" + group);
    if (!items.length || !badge) return;

    const errors = items.filter((i) => i.dataset.status === "error" || i.dataset.status === "fail");
    const warns = items.filter((i) => i.dataset.status === "warning");
    const infos = items.filter((i) => i.dataset.status === "info");

    if (errors.length > 0) {
        badge.textContent = `✗ ${errors.length} error${errors.length > 1 ? "s" : ""}`;
        badge.className = "fp-check-row-badge fp-check-row-badge--fail";
    } else if (warns.length > 0) {
        badge.textContent = `⚠ ${warns.length} warning${warns.length > 1 ? "s" : ""}`;
        badge.className = "fp-check-row-badge fp-check-row-badge--warn";
    } else if (infos.length > 0) {
        badge.textContent = `ℹ ${infos.length} note${infos.length > 1 ? "s" : ""}`;
        badge.className = "fp-check-row-badge fp-check-row-badge--info";
    } else {
        badge.textContent = "✓ Pass";
        badge.className = "fp-check-row-badge fp-check-row-badge--pass";
    }

    checkList.dataset.loaded = "1";
}

/**
 * Open the details modal for a group, copying the already-loaded check items.
 */
function openCheckModal(group) {
    const src = document.getElementById("cl-" + group);
    const body = document.getElementById("modal-body-" + group);
    const dialog = document.getElementById("modal-" + group);
    if (!src || !body || !dialog) return;

    // Populate modal with the already-loaded check items
    body.innerHTML = src.dataset.loaded
        ? src.innerHTML
        : '<div class="check-item loading"><div class="check-content"><div class="check-name">Loading…</div></div></div>';

    // Attach backdrop-click close once
    if (!dialog.dataset.closeReady) {
        dialog.dataset.closeReady = "1";
        dialog.addEventListener("click", (e) => {
            if (e.target === dialog) dialog.close();
        });
    }

    dialog.showModal();
}
