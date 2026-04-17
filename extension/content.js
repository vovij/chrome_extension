chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "SHOW_SEENIT_BANNER") {
    showBanner(msg.matches || [], msg.novelty || null, msg.noveltyDetails || null);
  }
});

function showBanner(matches, novelty, details) {
  // If banner exists, update it rather than doing nothing (helps while testing)
  const existing = document.getElementById("seenit-banner");
  if (existing) existing.remove();

  const banner = document.createElement("div");
  banner.id = "seenit-banner";

  const hasMatches = Array.isArray(matches) && matches.length > 0;

  //  Novelty percentage (with fallback)
  let noveltyHtml = "";
  let whatsNewHtml = "";
    
  if (hasMatches) {
    if (novelty && typeof novelty.novelty_score === "number") {
      noveltyHtml = `
        <div style="margin-top:8px;font-size:12px;color:#93c5fd">
          Novelty: <b>${Math.round(novelty.novelty_score * 100)}%</b>
          <span style="opacity:0.9">(${novelty.interpretation || "—"})</span>
        </div>
      `;
    } else {
      noveltyHtml = `
        <div style="margin-top:8px;font-size:12px;color:#93c5fd">
          Novelty: not enough history to estimate
        </div>
      `;
    }
  }

  //  Novelty details: prefer summary paragraph, fallback to bullet list
  const summary = (details && typeof details.summary === "string") ? details.summary.trim() : "";
  const newEntities = (details && Array.isArray(details.new_entities)) ? details.new_entities : [];
  const newNumbers  = (details && Array.isArray(details.new_numbers)) ? details.new_numbers : [];

  if (summary) {
    whatsNewHtml = `
      <div style="margin-top:8px;font-size:12px;color:#a7f3d0">
        <div style="font-weight:600;margin-bottom:4px">Here's what's likely new:</div>
        <div id="seenit-summary" style="line-height:1.4;opacity:0.95;max-height:120px;overflow:hidden;transition:max-height 0.2s ease">
          ${escapeHtml(summary)}
        </div>
        <div id="seenit-expand" style="margin-top:4px;font-size:11px;cursor:pointer;text-decoration:underline;opacity:0.9">
          Expand ▼
        </div>
      </div>
    `;
  } else if (newEntities.length || newNumbers.length) {
    const items = [
      ...newEntities.map(e => `Mentions "${escapeHtml(e)}"`),
      ...newNumbers.map(n => `Adds figure "${escapeHtml(n)}"`)
    ];

    whatsNewHtml = `
      <div style="margin-top:8px;font-size:12px;color:#a7f3d0">
        <div style="font-weight:600;margin-bottom:4px">What's likely new:</div>
        ${items.map(i => `<div>• ${i}</div>`).join("")}
      </div>
    `;
  } else if (hasMatches && novelty && novelty.novelty_score <= 0.3) {
    whatsNewHtml = `
      <div style="margin-top:6px;font-size:12px;color:#a7f3d0;opacity:0.9">
        <b>What's likely new:</b> No new entities or figures detected (content appears mostly repeated).
      </div>
    `;
  }

  // Banner HTML
  banner.innerHTML = `
    <div style="font-weight:600">👀 SeenIt</div>

    <div style="font-size:13px;margin-top:4px">
      ${hasMatches
        ? `You've read ${matches.length} similar article${matches.length === 1 ? "" : "s"}`
        : `First time you've seen this story (in your SeenIt history)`
      }
    </div>

    ${noveltyHtml}
    ${whatsNewHtml}

    ${hasMatches ? `
      <div style="margin-top:6px">
        ${matches.slice(0, 3).map(m =>
          `<div style="font-size:12px">• ${escapeHtml(m.title || "")}</div>`
        ).join("")}
      </div>
    ` : ""}

    <div style="margin-top:8px;font-size:12px;display:flex;gap:12px">
      <span id="seenit-hide" style="cursor:pointer;text-decoration:underline">Hide</span>
    </div>
  `;

  banner.style.cssText = `
    position: fixed;
    top: 16px;
    right: 16px;
    width: 500px;
    max-height: 85vh;
    overflow-y: auto;
    z-index: 999999;
    background: #111827;
    color: white;
    padding: 12px;
    border-radius: 8px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.25);
    font-family: system-ui, sans-serif;
  `;

  banner.querySelector("#seenit-hide").onclick = () => banner.remove();

  document.body.appendChild(banner);

  const expandBtn = banner.querySelector("#seenit-expand");
  const summaryEl = banner.querySelector("#seenit-summary");
  if (expandBtn && summaryEl) {
    const checkOverflow = () => {
      const overflows = summaryEl.scrollHeight > summaryEl.clientHeight;
      expandBtn.style.display = overflows ? "block" : "none";
    };
    requestAnimationFrame(checkOverflow);
    let expanded = false;
    expandBtn.onclick = () => {
      expanded = !expanded;
      summaryEl.style.maxHeight = expanded ? "none" : "120px";
      summaryEl.style.overflow = expanded ? "visible" : "hidden";
      expandBtn.textContent = expanded ? "Collapse ▲" : "Expand ▼";
    };
  }
}

// small helper to prevent HTML injection in titles
function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
