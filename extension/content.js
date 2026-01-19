chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "SHOW_SEENIT_BANNER") {
    showBanner(msg.matches);
  }
});

function showBanner(matches) {
  if (document.getElementById("seenit-banner")) return;

  const banner = document.createElement("div");
  banner.id = "seenit-banner";

  banner.innerHTML = `
    <div style="font-weight:600">👀 SeenIt</div>
    <div style="font-size:13px;margin-top:4px">
      You've read ${matches.length} similar article(s)
    </div>
    <div style="margin-top:6px">
      ${matches.slice(0, 3).map(m =>
        `<div style="font-size:12px">
          • ${m.title}
        </div>`
      ).join("")}
    </div>
    <div style="margin-top:8px;font-size:12px;cursor:pointer;text-decoration:underline">
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

  banner.querySelector("div:last-child").onclick = () => banner.remove();

  document.body.appendChild(banner);
}
