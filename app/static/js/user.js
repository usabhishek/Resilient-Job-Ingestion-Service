(function () {
    const LIMIT = 10;
    let tab = "all";                 // "all" or "applied"
    let page = 1, pages = 1, timer = null;
    let items = [];                  // jobs shown on the current page
    const selected = new Set();      // ids ticked on the current page
    const $ = (id) => document.getElementById(id);
    const boards = { greenhouse: "cloudflare", lever: "netflix" };

    $("source").addEventListener("change", () => { $("board").value = boards[$("source").value]; });

    /* ---------------------------------------------------------------- fetch jobs */
    $("ingest-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const btn = $("fetch-btn"), box = $("ingest-msg");
        btn.disabled = true; btn.textContent = "Fetching…";
        try {
            const days = $("period").value;
            const r = await api("/api/ingest", { method: "POST", body: {
                source: $("source").value,
                board_token: $("board").value.trim(),
                allow_fallback: $("fallback").checked,
                posted_within_days: days ? Number(days) : null } });
            if (r.status === "FAILED") {
                showMessage(box, r.error_message || "Could not fetch jobs.", false);
            } else if (r.status === "EMPTY_RESPONSE") {
                showMessage(box, "This company has no open jobs right now.", true);
            } else {
                let text = `Saved ${r.new_count} new job(s)`;
                if (r.duplicate_count) text += `, ${r.duplicate_count} already saved`;
                if (r.skipped_old_count) text += `, ${r.skipped_old_count} outside the selected period skipped`;
                if (r.fallback_used) text += ` (backup source used: ${r.fallback_source_name})`;
                showMessage(box, text + ".", true);
                tab = "all"; page = 1; syncTabs(); await loadJobs();
            }
        } catch (err) {
            showMessage(box, err.message, false);
        } finally {
            btn.disabled = false; btn.textContent = "Fetch jobs";
        }
    });

    /* ----------------------------------------------------------- tabs, search, paging */
    document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
        tab = button.dataset.tab; page = 1; syncTabs(); loadJobs();
    }));
    function syncTabs() {
        document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    }

    $("search").addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => { page = 1; loadJobs(); }, 300);
    });
    $("prev").addEventListener("click", () => { if (page > 1) { page--; loadJobs(); } });
    $("next").addEventListener("click", () => { if (page < pages) { page++; loadJobs(); } });

    /* ---------------------------------------------------------------- load + render */
    async function loadJobs() {
        const query = new URLSearchParams({ page, limit: LIMIT });
        const term = $("search").value.trim();
        if (term) query.set("search", term);
        if (tab === "applied") query.set("applied", "true");
        const data = await api("/api/jobs?" + query);
        pages = data.pages;
        if (page > pages) { page = pages; return loadJobs(); }   // e.g. the last jobs on a page were deleted

        items = data.items;
        selected.clear();
        const label = tab === "applied" ? "Applied jobs" : "All jobs";
        $("list-title").firstChild.textContent = label + " ";
        $("total").textContent = data.total ? `(${data.total})` : "";

        const list = $("jobs");
        list.replaceChildren();
        if (!items.length) list.append(el("div", { class: "empty" }, emptyText(term)));
        for (const job of items) list.append(renderJob(job));

        $("bulk").classList.toggle("hidden", !items.length);
        $("page-info").textContent = data.total ? `Page ${page} of ${pages}` : "";
        $("prev").disabled = page <= 1;
        $("next").disabled = page >= pages;
        document.querySelector(".pager").classList.toggle("hidden", data.total <= LIMIT);
        updateBulk();
    }

    function emptyText(term) {
        if (term) return "No jobs match your search.";
        if (tab === "applied") return "You haven't applied to any job yet. Press “Apply” on a job to track it here.";
        return "No jobs yet. Choose a company above and press “Fetch jobs”.";
    }

    function renderJob(job) {
        const meta = [job.company, job.location];
        if (job.posted_at) meta.push("posted " + new Date(job.posted_at).toLocaleDateString());

        const checkbox = el("input", { type: "checkbox", "aria-label": "Select " + job.title });
        checkbox.checked = selected.has(job.id);
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) selected.add(job.id); else selected.delete(job.id);
            updateBulk();
        });

        const text = el("div", {}, el("div", { class: "job-title" }, job.title),
                                   el("div", { class: "muted" }, meta.join(" · ")));
        if (job.applied_at) {
            text.append(el("span", { class: "pill ok" }, "✓ Applied on " + new Date(job.applied_at).toLocaleDateString()));
        }

        const actions = el("div", { class: "job-actions" });
        const safeUrl = /^https?:\/\//.test(job.job_url) ? job.job_url : null;
        if (job.applied_at) {
            if (safeUrl) actions.append(el("a", { href: safeUrl, target: "_blank", rel: "noopener noreferrer" }, "View"));
            actions.append(el("button", { type: "button", class: "btn btn-ghost btn-sm",
                onclick: () => setApplied(job, false) }, "Undo"));
        } else if (safeUrl) {
            // A real link, so the browser opens the job page; we also record that the user applied.
            actions.append(el("a", { href: safeUrl, target: "_blank", rel: "noopener noreferrer",
                class: "btn btn-primary btn-sm", onclick: () => setApplied(job, true) }, "Apply ↗"));
        }
        return el("div", { class: "job" }, el("label", { class: "job-main" }, checkbox, text), actions);
    }

    async function setApplied(job, applied) {
        try { await api("/api/jobs/" + job.id, { method: "PATCH", body: { applied } }); await loadJobs(); }
        catch (err) { alert(err.message); }
    }

    /* ------------------------------------------------------------------ bulk delete */
    $("select-all").addEventListener("change", () => {
        selected.clear();
        if ($("select-all").checked) items.forEach((job) => selected.add(job.id));
        document.querySelectorAll("#jobs .job-main input[type=checkbox]").forEach((box) => {
            box.checked = $("select-all").checked;
        });
        updateBulk();
    });

    function updateBulk() {
        const n = selected.size;
        $("selected-count").textContent = n + " selected";
        $("delete-selected").disabled = n === 0;
        $("delete-selected").textContent = n ? `Delete selected (${n})` : "Delete selected";
        const all = $("select-all");
        all.checked = items.length > 0 && n === items.length;
        all.indeterminate = n > 0 && n < items.length;
    }

    $("delete-selected").addEventListener("click", async () => {
        const ids = [...selected];
        const appliedCount = items.filter((j) => selected.has(j.id) && j.applied_at).length;
        let question = `Delete ${ids.length} selected job(s)?`;
        if (appliedCount) question += `\n${appliedCount} of them ${appliedCount === 1 ? "is" : "are"} marked as applied and will also disappear from your Applied list.`;
        if (!confirm(question)) return;
        try { await api("/api/jobs/bulk-delete", { method: "POST", body: { ids } }); await loadJobs(); }
        catch (err) { alert(err.message); }
    });

    loadJobs();
})();
