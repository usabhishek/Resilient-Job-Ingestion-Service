(function () {
    const LIMIT = 10;
    let page = 1, pages = 1;
    const $ = (id) => document.getElementById(id);

    async function loadSummary() {
        const s = await api("/api/admin/summary");
        $("s-users").textContent = s.users;
        $("s-jobs").textContent = s.jobs;
        $("s-runs").textContent = s.runs;
        const box = $("s-health");
        box.replaceChildren();
        for (const [name, info] of Object.entries(s.sources)) {
            const text = info.healthy ? `${name} ✓ ${Math.round(info.latency_ms)}ms` : `${name} ✗ down`;
            box.append(el("span", { class: "pill " + (info.healthy ? "ok" : "bad"), title: info.message }, text), " ");
        }
    }

    async function loadUsers() {
        const users = await api("/api/admin/users");
        const body = $("users-body");
        body.replaceChildren();
        for (const u of users) {
            const actions = el("td");
            if (u.role !== "admin") {
                actions.append(
                    el("button", { type: "button", class: "btn btn-ghost btn-sm", onclick: () => clearUser(u) }, "Clear ingestions"), " ",
                    el("button", { type: "button", class: "btn btn-danger btn-sm", onclick: () => deleteUser(u) }, "Delete user"));
            }
            body.append(el("tr", {},
                el("td", {}, u.name), el("td", {}, u.email), el("td", {}, u.role),
                el("td", {}, String(u.jobs)), el("td", {}, String(u.runs)),
                el("td", {}, fmtDate(u.last_ingestion_at)), actions));
        }
    }

    async function loadRuns() {
        const data = await api(`/api/admin/runs?page=${page}&limit=${LIMIT}`);
        pages = data.pages;
        const body = $("runs-body");
        body.replaceChildren();
        if (!data.items.length) {
            body.append(el("tr", {}, el("td", { colspan: "8", class: "empty" }, "No ingestions yet.")));
        }
        for (const r of data.items) {
            const cls = r.status === "SUCCESS" || r.status === "FALLBACK_SUCCESS" ? "ok"
                      : r.status === "PARTIAL" || r.status === "EMPTY_RESPONSE" ? "warn" : "bad";
            body.append(el("tr", {},
                el("td", {}, `${r.user_name} (${r.user_email})`),
                el("td", {}, r.source + (r.fallback_source ? " → " + r.fallback_source : "")),
                el("td", {}, el("span", { class: "pill " + cls }, r.status)),
                el("td", {}, String(r.fetched)), el("td", {}, String(r.new)),
                el("td", {}, String(r.duplicates)), el("td", {}, String(r.failed)),
                el("td", {}, fmtDate(r.started_at))));
        }
        $("page-info").textContent = `Page ${page} of ${pages} (${data.total} runs)`;
        $("prev").disabled = page <= 1;
        $("next").disabled = page >= pages;
    }

    async function refreshAll() { await Promise.all([loadSummary(), loadUsers(), loadRuns()]); }

    async function clearUser(u) {
        if (!confirm(`Delete all jobs and ingestions of ${u.email}? The account stays.`)) return;
        try { const r = await api(`/api/admin/users/${u.id}/ingestions`, { method: "DELETE" }); say(r.detail, true); await refreshAll(); }
        catch (err) { say(err.message, false); }
    }

    async function deleteUser(u) {
        if (!confirm(`Delete user ${u.email} and ALL of their data?`)) return;
        try { const r = await api(`/api/admin/users/${u.id}`, { method: "DELETE" }); say(r.detail, true); await refreshAll(); }
        catch (err) { say(err.message, false); }
    }

    function say(text, ok) { showMessage($("admin-msg"), text, ok); }

    $("clear-all").addEventListener("click", async () => {
        if (!confirm("Delete EVERY job and ingestion of EVERY user? This cannot be undone.")) return;
        try { const r = await api("/api/admin/ingestions", { method: "DELETE" }); say(r.detail, true); page = 1; await refreshAll(); }
        catch (err) { say(err.message, false); }
    });
    $("prev").addEventListener("click", () => { if (page > 1) { page--; loadRuns(); } });
    $("next").addEventListener("click", () => { if (page < pages) { page++; loadRuns(); } });

    refreshAll();
})();
