/**
 * Acdyon Ingestion Console Frontend Controller
 */

function updatePresetBoards() {
    const sourceSelect = document.getElementById("source-select");
    const boardInput = document.getElementById("board-token");
    if (sourceSelect.value === "greenhouse") {
        boardInput.value = "cloudflare";
    } else if (sourceSelect.value === "lever") {
        boardInput.value = "netflix";
    }
}

async function handleIngest(event) {
    event.preventDefault();

    const source = document.getElementById("source-select").value;
    const boardToken = document.getElementById("board-token").value.trim();
    const allowFallback = document.getElementById("allow-fallback").checked;

    const btn = document.getElementById("btn-ingest");
    const btnSpinner = document.getElementById("btn-spinner");
    const btnText = document.getElementById("btn-text");
    const resultDiv = document.getElementById("ingest-result");

    if (!boardToken) {
        alert("Please enter a valid board token.");
        return;
    }

    // UI Loading State
    btn.disabled = true;
    btnSpinner.classList.remove("hidden");
    btnText.textContent = "Ingesting & Pacing...";
    resultDiv.className = "ingest-result hidden";
    resultDiv.innerHTML = "";

    try {
        const response = await fetch("/api/ingest", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                source: source,
                board_token: boardToken,
                allow_fallback: allowFallback
            })
        });

        const data = await response.json();

        if (response.ok) {
            resultDiv.className = "ingest-result success";
            let statusBadge = `<strong style="text-transform: uppercase;">[${data.status}]</strong>`;
            let fallbackNotice = data.fallback_used ? ` (Fallback Source Used: <strong>${data.fallback_source_name}</strong>)` : "";
            
            resultDiv.innerHTML = `
                <div>
                    ${statusBadge} Ingestion run completed in <strong>${data.duration_ms}ms</strong>${fallbackNotice}.
                </div>
                <div style="margin-top: 0.35rem; font-size: 0.8rem;">
                    Fetched: <strong>${data.fetched_count}</strong> &bull; 
                    Valid: <strong>${data.valid_count}</strong> &bull; 
                    New Added: <strong style="color: #34d399;">+${data.new_count}</strong> &bull; 
                    Duplicates Skipped: <strong>${data.duplicate_count}</strong> &bull; 
                    Failed: <strong>${data.failed_count}</strong>
                </div>
            `;

            // Reload page smoothly after 1.5s to display updated metrics and tables
            setTimeout(() => {
                window.location.reload();
            }, 1800);
        } else {
            resultDiv.className = "ingest-result error";
            resultDiv.innerHTML = `<strong>Error:</strong> ${data.detail || "Ingestion request failed."}`;
        }
    } catch (err) {
        resultDiv.className = "ingest-result error";
        resultDiv.innerHTML = `<strong>Network Error:</strong> ${err.message}`;
    } finally {
        btn.disabled = false;
        btnSpinner.classList.add("hidden");
        btnText.textContent = "Execute Ingestion";
    }
}

function filterJobsTable() {
    const input = document.getElementById("job-search");
    const filter = input.value.toLowerCase();
    const rows = document.querySelectorAll("#jobs-table-body .job-row");

    rows.forEach(row => {
        const title = row.querySelector(".job-title-text")?.textContent.toLowerCase() || "";
        const company = row.querySelector(".company-text")?.textContent.toLowerCase() || "";
        const location = row.querySelector(".location-text")?.textContent.toLowerCase() || "";
        
        if (title.includes(filter) || company.includes(filter) || location.includes(filter)) {
            row.style.display = "";
        } else {
            row.style.display = "none";
        }
    });
}
