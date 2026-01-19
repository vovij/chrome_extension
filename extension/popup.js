// SeenIt Popup — shows CURRENT page + LIST of clusters
// Reads from chrome.storage.local.clusters

const TRACKED_SITES = [
  "bbc.co.uk",
  "reuters.com",
  "cnn.com",
  "nytimes.com",
  "theguardian.com",
];

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();

  loadCurrent();
  loadClusters();
  loadStats();

  document.getElementById("refresh-current")?.addEventListener("click", loadCurrent);
});

// ---------------- Utils ----------------

function isTrackedSite(url) {
  try {
    const hostname = new URL(url).hostname.replace("www.", "");
    return TRACKED_SITES.some((site) => hostname.includes(site));
  } catch {
    return false;
  }
}

function escapeHtml(s) {
  return (s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Find cluster which contains url
function findClusterForUrl(clustersObj, url) {
  const clusters = Object.values(clustersObj || {});
  return (
    clusters.find((c) => c.currentUrl === url) ||
    clusters.find((c) => (c.articles || []).some((a) => a.url === url)) ||
    null
  );
}


// ---------------- Tabs ----------------

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".content").forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      document.getElementById(tab.dataset.tab).classList.add("active");

      if (tab.dataset.tab === "current") loadCurrent();
      if (tab.dataset.tab === "list") loadClusters();
      if (tab.dataset.tab === "settings") loadStats();
    });
  });
}

// ---------------- Current ----------------

function loadCurrent() {
  const titleEl = document.querySelector("#page-info .page-title");
  const urlEl = document.querySelector("#page-info .page-url");
  const trackingEl = document.getElementById("tracking-status");
  const matchesEl = document.getElementById("current-matches");

  titleEl.textContent = "Loading...";
  urlEl.textContent = "";
  trackingEl.style.display = "none";
  matchesEl.innerHTML = "";

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs?.[0];
    if (!tab?.url) {
      titleEl.textContent = "No active tab";
      return;
    }

    titleEl.textContent = tab.title || "Untitled";
    urlEl.textContent = tab.url;

    if (isTrackedSite(tab.url)) {
      trackingEl.style.display = "block";
    } else {
      trackingEl.style.display = "none";
    }

    chrome.storage.local.get(["clusters"], (res) => {
      const clusters = res.clusters || {};
      const cluster = findClusterForUrl(clusters, tab.url);

      if (!cluster) {
        matchesEl.innerHTML = `
          <p style="color:#6b7280;margin-top:6px;font-size:13px">
            Not tracked yet for this page.
          </p>
        `;
        return;
      }

      const others = (cluster.articles || []).filter((a) => a.url !== tab.url);

      if (others.length === 0) {
        matchesEl.innerHTML = `
          <div class="list-item">
            <div style="font-weight:600;margin-bottom:6px">Similar articles</div>
            <div style="color:#6b7280;font-size:13px">No similar matches saved yet.</div>
          </div>
        `;
        return;
      }

      // sort by similarity desc
      others.sort((a, b) => (b.similarity || 0) - (a.similarity || 0));

      matchesEl.innerHTML = `
        <div class="list-item">
          <div style="font-weight:600;margin-bottom:6px">Similar articles</div>
          <ul style="padding-left:16px;margin:0">
            ${others
              .map(
                (a) => `
              <li style="font-size:13px;margin-bottom:6px">
                <a href="${escapeHtml(a.url)}" target="_blank">${escapeHtml(a.title)}</a>
                <span style="color:#6b7280;font-size:11px">
                  (${(((a.similarity || 0) * 100)).toFixed(0)}%)
                </span>
              </li>`
              )
              .join("")}
          </ul>
          <div style="font-size:11px;color:#9ca3af;margin-top:6px">
            Last visited: ${cluster.lastVisited ? new Date(cluster.lastVisited).toLocaleString() : "—"}
          </div>
        </div>
      `;
    });
  });
}

// ---------------- List ----------------

function loadClusters() {
  chrome.storage.local.get(["clusters"], (res) => {
    const clusters = res.clusters || {};
    const container = document.getElementById("seen-list");

    let entries = Object.values(clusters);

    if (entries.length === 0) {
      container.innerHTML = `<p style="color:#6b7280">No articles yet</p>`;
      return;
    }

    // newest first
    entries.sort((a, b) => new Date(b.lastVisited || 0) - new Date(a.lastVisited || 0));

    container.innerHTML = entries
      .map(
        (cluster) => `
      <div class="list-item">
        <div style="font-weight:600;margin-bottom:6px">
          📌 ${escapeHtml(cluster.representativeTitle || "Cluster")}
        </div>

        <ul style="padding-left:16px;margin:0">
          ${(cluster.articles || [])
            .slice()
            .sort((a, b) => (b.similarity || 0) - (a.similarity || 0))
            .map(
              (a) => `
              <li style="font-size:13px;margin-bottom:6px">
                <a href="${escapeHtml(a.url)}" target="_blank">${escapeHtml(a.title)}</a>
                <span style="color:#6b7280;font-size:11px">
                  (${(((a.similarity || 0) * 100)).toFixed(0)}%)
                </span>
              </li>
            `
            )
            .join("")}
        </ul>

        <div style="font-size:11px;color:#9ca3af;margin-top:6px">
          Last visited: ${cluster.lastVisited ? new Date(cluster.lastVisited).toLocaleString() : "—"}
        </div>
      </div>
    `
      )
      .join("");
  });
}

// ---------------- Stats ----------------

function loadStats() {
  chrome.storage.local.get(["clusters"], (res) => {
    const clusters = res.clusters || {};

    const totalClusters = Object.keys(clusters).length;
    document.getElementById("total-tracked").textContent = totalClusters;

    const today = new Date().toDateString();
    let todayCount = 0;

    Object.values(clusters).forEach((c) => {
      if (c?.lastVisited && new Date(c.lastVisited).toDateString() === today) {
        todayCount++;
      }
    });

    document.getElementById("today-tracked").textContent = todayCount;
  });
}

// ---------------- Clear ----------------

document.getElementById("clear-all")?.addEventListener("click", () => {
  if (!confirm("Clear all tracked articles?")) return;

  chrome.storage.local.set({ clusters: {} }, () => {
    loadCurrent();
    loadClusters();
    loadStats();
  });
});
