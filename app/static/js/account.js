(function () {
    const $ = (id) => document.getElementById(id);

    $("name-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
            const me = await api("/api/me", { method: "PATCH", body: { name: $("name").value.trim() } });
            showMessage($("name-msg"), "Name updated.", true);
            const welcome = document.querySelector(".welcome");
            if (welcome) welcome.textContent = "Welcome, " + me.name;
        } catch (err) { showMessage($("name-msg"), err.message, false); }
    });

    $("password-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
            await api("/api/me/password", { method: "POST", body: {
                current_password: $("current").value, new_password: $("new").value } });
            showMessage($("password-msg"), "Password changed.", true);
            $("password-form").reset();
        } catch (err) { showMessage($("password-msg"), err.message, false); }
    });

    $("delete-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!confirm("Delete your account and ALL your jobs? This cannot be undone.")) return;
        try {
            await api("/api/me/delete", { method: "POST", body: { password: $("delete-password").value } });
            window.location.href = "/login?msg=Your+account+was+deleted.";
        } catch (err) { showMessage($("delete-msg"), err.message, false); }
    });
})();
