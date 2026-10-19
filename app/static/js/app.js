/* Shared helpers: theme toggle, API calls, safe DOM building. */
(function () {
    const root = document.documentElement;
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
        toggle.addEventListener("click", function () {
            const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
            root.setAttribute("data-theme", next);
            localStorage.setItem("theme", next);
        });
    }
})();

/* fetch wrapper: JSON in/out, redirects to /login when the session has expired */
async function api(url, options = {}) {
    const init = { credentials: "same-origin", headers: {}, ...options };
    if (init.body && typeof init.body !== "string") {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(init.body);
    }
    const res = await fetch(url, init);
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Please log in"); }
    if (res.status === 204) return null;
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
        const detail = data && data.detail;
        throw new Error(typeof detail === "string" ? detail : "Something went wrong.");
    }
    return data;
}

/* Build elements with textContent only (no innerHTML), so data can never inject HTML. */
function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (key === "class") node.className = value;
        else if (key === "onclick") node.addEventListener("click", value);
        else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
}

function showMessage(box, text, ok) {
    box.textContent = text;
    box.className = "alert " + (ok ? "success" : "error");
}

function fmtDate(value) {
    return value ? new Date(value).toLocaleString() : "–";
}
