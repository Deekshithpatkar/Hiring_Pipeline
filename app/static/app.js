// Mini Hiring Pipeline - Vanilla JS
const ORDERED_STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"];
const ALL_STAGES = [...ORDERED_STAGES, "Rejected"];

// Document ready
document.addEventListener("DOMContentLoaded", () => {
    loadBoard();
});

// --- Board Operations ---

async function loadBoard() {
    try {
        const response = await fetch("/api/candidates");
        if (!response.ok) {
            console.error("Failed to load candidates", response.status);
            return;
        }

        const data = await response.json();
        const grouped = data.grouped || {};

        // Render each stage column
        ALL_STAGES.forEach(stage => {
            const listEl = document.getElementById(`list-${stage}`);
            const countEl = document.getElementById(`count-${stage}`);
            const candidates = grouped[stage] || [];

            if (countEl) countEl.textContent = candidates.length;
            if (!listEl) return;

            listEl.innerHTML = "";

            if (candidates.length === 0) {
                listEl.innerHTML = `<div class="empty-state">No candidates</div>`;
                return;
            }

            candidates.forEach(cand => {
                const card = createCandidateCard(cand);
                listEl.appendChild(card);
            });
        });
    } catch (err) {
        console.error("Error loading board:", err);
    }
}

function createCandidateCard(cand) {
    const card = document.createElement("div");
    card.className = "candidate-card";
    card.id = `candidate-card-${cand.id}`;

    const currentStage = cand.current_stage;
    const isHired = currentStage === "Hired";
    const isRejected = currentStage === "Rejected";
    const isTerminal = isHired || isRejected;

    // Determine allowed forward stage
    let nextStage = null;
    if (!isTerminal && ORDERED_STAGES.includes(currentStage)) {
        const idx = ORDERED_STAGES.indexOf(currentStage);
        if (idx + 1 < ORDERED_STAGES.length) {
            nextStage = ORDERED_STAGES[idx + 1];
        }
    }

    // Card Header & Details
    const header = document.createElement("div");
    header.className = "card-header";

    const title = document.createElement("div");
    title.className = "card-title";
    title.textContent = cand.name;
    title.title = "Click to view full history & audit trail";
    title.onclick = () => openCandidateModal(cand.id);

    header.appendChild(title);

    const email = document.createElement("div");
    email.className = "card-email";
    email.textContent = cand.email;

    // Time in stage meta
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.innerHTML = `<span>⏱️</span> <span>${cand.time_in_current_stage_human} in stage</span>`;

    // Actions
    const actions = document.createElement("div");
    actions.className = "card-actions";

    if (nextStage) {
        const advBtn = document.createElement("button");
        advBtn.className = "btn btn-advance";
        advBtn.textContent = `Advance → ${nextStage}`;
        advBtn.onclick = () => handleTransition(cand.id, nextStage, card);
        actions.appendChild(advBtn);
    }

    if (!isTerminal) {
        const rejBtn = document.createElement("button");
        rejBtn.className = "btn btn-reject";
        rejBtn.textContent = "Reject ✕";
        rejBtn.onclick = () => handleTransition(cand.id, "Rejected", card);
        actions.appendChild(rejBtn);
    }

    if (isHired) {
        const badge = document.createElement("span");
        badge.className = "terminal-badge terminal-badge-hired";
        badge.textContent = "✓ Hired";
        actions.appendChild(badge);
    } else if (isRejected) {
        const badge = document.createElement("span");
        badge.className = "terminal-badge terminal-badge-rejected";
        badge.textContent = "✕ Rejected";
        actions.appendChild(badge);
    }

    // Inline error container
    const errorBox = document.createElement("div");
    errorBox.className = "card-error";
    errorBox.id = `card-error-${cand.id}`;
    errorBox.style.display = "none";

    card.appendChild(header);
    card.appendChild(email);
    card.appendChild(meta);
    card.appendChild(actions);
    card.appendChild(errorBox);

    return card;
}

// --- Add Candidate ---

async function handleAddCandidate(event) {
    event.preventDefault();
    const nameInput = document.getElementById("new-candidate-name");
    const emailInput = document.getElementById("new-candidate-email");
    const errorBox = document.getElementById("add-candidate-error");
    const submitBtn = document.getElementById("add-candidate-btn");

    errorBox.style.display = "none";
    errorBox.textContent = "";

    const name = nameInput.value.trim();
    const email = emailInput.value.trim();

    if (!name || !email) {
        errorBox.textContent = "Both name and email are required.";
        errorBox.style.display = "block";
        return;
    }

    submitBtn.disabled = true;
    try {
        const response = await fetch("/api/candidates", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, email }),
        });

        const data = await response.json();

        if (!response.ok) {
            errorBox.textContent = data.detail || "Failed to add candidate.";
            errorBox.style.display = "block";
            return;
        }

        // Successfully created: reset form and refresh board immediately
        nameInput.value = "";
        emailInput.value = "";
        await loadBoard();
    } catch (err) {
        errorBox.textContent = "Network error while creating candidate.";
        errorBox.style.display = "block";
    } finally {
        submitBtn.disabled = false;
    }
}

// --- Advance / Reject Stage Transition ---

async function handleTransition(candidateId, newStage, cardElement) {
    const errorBox = cardElement.querySelector(".card-error");
    if (errorBox) {
        errorBox.style.display = "none";
        errorBox.textContent = "";
    }

    try {
        const response = await fetch(`/api/candidates/${candidateId}/transition`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_stage: newStage }),
        });

        const data = await response.json();

        if (!response.ok) {
            // Show backend's specific error message inline — NO confirmation popups!
            if (errorBox) {
                errorBox.textContent = data.detail || `Cannot transition to ${newStage}`;
                errorBox.style.display = "block";
            }
            return;
        }

        // Successfully moved: re-render board
        await loadBoard();
    } catch (err) {
        if (errorBox) {
            errorBox.textContent = "Network error during transition.";
            errorBox.style.display = "block";
        }
    }
}

// --- Candidate Detail Modal (Audit Trail) ---

async function openCandidateModal(candidateId) {
    const modal = document.getElementById("candidate-modal");
    const nameEl = document.getElementById("modal-candidate-name");
    const emailEl = document.getElementById("modal-candidate-email");
    const stageEl = document.getElementById("modal-candidate-stage");
    const durEl = document.getElementById("modal-candidate-duration");
    const historyList = document.getElementById("modal-history-list");
    const errorBox = document.getElementById("modal-error-message");

    errorBox.style.display = "none";
    historyList.innerHTML = `<div style="color:#64748b; font-size:0.85rem;">Loading audit trail...</div>`;
    modal.style.display = "flex";

    try {
        const response = await fetch(`/api/candidates/${candidateId}`);
        if (!response.ok) {
            errorBox.textContent = "Could not load candidate details.";
            errorBox.style.display = "block";
            return;
        }

        const data = await response.json();
        nameEl.textContent = data.name;
        emailEl.textContent = data.email;
        stageEl.textContent = data.current_stage;
        durEl.textContent = `${data.time_in_current_stage_human} in stage`;

        historyList.innerHTML = "";
        const history = data.history || [];

        if (history.length === 0) {
            historyList.innerHTML = `<div style="color:#64748b;">No events recorded.</div>`;
            return;
        }

        history.forEach((evt, idx) => {
            const item = document.createElement("div");
            item.className = `timeline-item ${evt.is_current ? "current-item" : ""}`;

            const dateStr = new Date(evt.timestamp).toLocaleString();
            const fromText = evt.from_stage ? `from ${evt.from_stage} → ` : "Initial Application → ";

            item.innerHTML = `
                <div class="timeline-stage">
                    ${fromText}<strong>${evt.to_stage}</strong>
                    ${evt.is_current ? '<span class="status-label" style="margin-left:0.5rem; color:#34d399; font-weight:700;">(Current)</span>' : ''}
                </div>
                <div class="timeline-meta">
                    <span>📅 ${dateStr}</span>
                    <span>⏱️ Duration: <strong>${evt.duration_human}</strong></span>
                </div>
            `;
            historyList.appendChild(item);
        });
    } catch (err) {
        errorBox.textContent = "Error fetching candidate details.";
        errorBox.style.display = "block";
    }
}

function closeCandidateModal() {
    const modal = document.getElementById("candidate-modal");
    if (modal) modal.style.display = "none";
}

function handleModalBackdropClick(event) {
    if (event.target.id === "candidate-modal") {
        closeCandidateModal();
    }
}

// Close modal on Escape key
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeCandidateModal();
    }
});

// --- Live Search ---

let searchDebounceTimer = null;

function handleSearchInput(event) {
    const q = event.target.value.trim();
    const clearBtn = document.getElementById("clear-search-btn");
    const feedbackBox = document.getElementById("search-feedback");
    const resultsContainer = document.getElementById("search-results-container");

    if (clearBtn) clearBtn.style.display = q ? "inline-block" : "none";

    clearTimeout(searchDebounceTimer);
    if (!q) {
        feedbackBox.style.display = "none";
        resultsContainer.style.display = "none";
        loadBoard();
        return;
    }

    searchDebounceTimer = setTimeout(async () => {
        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const data = await response.json();

            feedbackBox.style.display = "block";
            feedbackBox.className = "search-feedback";

            if (!data.success) {
                feedbackBox.className = "search-feedback error-feedback";
                feedbackBox.textContent = data.explanation || "Invalid search query.";
                resultsContainer.style.display = "none";
                filterBoardWithResults([]);
                return;
            }

            if (data.explanation) {
                feedbackBox.textContent = data.explanation;
            } else if (data.filters_applied && data.filters_applied.length > 0) {
                feedbackBox.textContent = `Filters active: ${data.filters_applied.join(" • ")} (${data.count} found)`;
            } else {
                feedbackBox.textContent = `${data.count} candidate(s) found`;
            }

            renderSearchResults(data.results || []);
            filterBoardWithResults(data.results || []);
        } catch (err) {
            console.error("Search error:", err);
        }
    }, 200);
}

function clearSearch() {
    const searchInput = document.getElementById("search-input");
    const clearBtn = document.getElementById("clear-search-btn");
    const feedbackBox = document.getElementById("search-feedback");
    const resultsContainer = document.getElementById("search-results-container");

    if (searchInput) searchInput.value = "";
    if (clearBtn) clearBtn.style.display = "none";
    if (feedbackBox) feedbackBox.style.display = "none";
    if (resultsContainer) resultsContainer.style.display = "none";

    // Restore all candidates on board
    loadBoard();
}

function renderSearchResults(results) {
    const container = document.getElementById("search-results-container");
    if (!container) return;

    if (results.length === 0) {
        container.style.display = "none";
        return;
    }

    container.innerHTML = "";
    container.style.display = "block";

    results.forEach(cand => {
        const item = document.createElement("div");
        item.className = "search-result-item";
        item.onclick = () => openCandidateModal(cand.id);

        item.innerHTML = `
            <div>
                <strong>${cand.name}</strong> <span style="font-size:0.8rem; color:#64748b;">(${cand.email})</span>
            </div>
            <div style="display:flex; align-items:center; gap:0.5rem;">
                <span style="font-size:0.8rem; font-weight:700; color:#f5b700;">${cand.current_stage}</span>
                <span class="duration-pill">${cand.time_in_current_stage_human} in stage</span>
            </div>
        `;
        container.appendChild(item);
    });
}

function filterBoardWithResults(matchedCandidates) {
    const matchedIds = new Set(matchedCandidates.map(c => c.id));
    ALL_STAGES.forEach(stage => {
        const listEl = document.getElementById(`list-${stage}`);
        const countEl = document.getElementById(`count-${stage}`);
        if (!listEl) return;

        let visibleCount = 0;
        const cards = listEl.querySelectorAll(".candidate-card");
        cards.forEach(card => {
            const cid = card.id.replace("candidate-card-", "");
            if (matchedIds.has(cid)) {
                card.style.display = "flex";
                visibleCount++;
            } else {
                card.style.display = "none";
            }
        });
        if (countEl) countEl.textContent = visibleCount;
    });
}
