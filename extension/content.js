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

  // ---------- Novelty percentage (with fallback) ----------
  let noveltyHtml = "";
  let whatsNewPlaceholder = "";
    
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

   // --- NEW placeholder line ---
  whatsNewPlaceholder = `
    <div style="margin-top:6px;font-size:12px;color:#a7f3d0">
      <b>Here’s what’s likely new:</b> <span style="opacity:0.8">(coming soon…)</span>
    </div>
  `;
      
  }

  // ---------- Novelty details (safe even if backend doesn't send it yet) ----------
  const newEntities = (details && Array.isArray(details.new_entities)) ? details.new_entities : [];
  const newNumbers  = (details && Array.isArray(details.new_numbers)) ? details.new_numbers : [];

  let whatsNewHtml = "";
  if (newEntities.length || newNumbers.length) {
    const items = [
      ...newEntities.map(e => `Mentions "${e}"`),
      ...newNumbers.map(n => `Adds figure "${n}"`)
    ].slice(0, 3);

    whatsNewHtml = `
      <div style="margin-top:8px;font-size:12px;color:#a7f3d0">
        <div style="font-weight:600;margin-bottom:4px">What's likely new:</div>
        ${items.map(i => `<div>• ${i}</div>`).join("")}
      </div>
    `;
  }

  // ---------- Banner HTML ----------
  banner.innerHTML = `
    <div style="font-weight:600">👀 SeenIt</div>

    <div style="font-size:13px;margin-top:4px">
      ${hasMatches
        ? `You've read ${matches.length} similar article${matches.length === 1 ? "" : "s"}`
        : `First time you've seen this story (in your SeenIt history)`
      }
    </div>

    ${noveltyHtml}
    ${whatsNewPlaceholder}

    ${hasMatches ? `
      <div style="margin-top:6px">
        ${matches.slice(0, 3).map(m =>
          `<div style="font-size:12px">• ${escapeHtml(m.title || "")}</div>`
        ).join("")}
      </div>
    ` : ""}

    <div id="seenit-hide" style="margin-top:8px;font-size:12px;cursor:pointer;text-decoration:underline">
      Hide
    </div>
  `;

  banner.style.cssText = `
    position: fixed;
    top: 16px;
    right: 16px;
    width: 280px;
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
}

// prevent HTML injection in titles
function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
