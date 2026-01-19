// background.js — SeenIt (MV3)
// SPA-safe, saves to chrome.storage.local.clusters for popup

const API_BASE_URL = "http://localhost:8000";

// News websites to monitor
const TRACKED_SITES = [
  "bbc.co.uk",
  "reuters.com",
  "cnn.com",
  "nytimes.com",
  "theguardian.com",
];

// ---------- Utils ----------

function isTrackedSite(url) {
  try {
    const hostname = new URL(url).hostname.replace("www.", "");
    return TRACKED_SITES.some((site) => hostname.includes(site));
  } catch {
    return false;
  }
}

// ---------- Article Extraction ----------

async function extractArticle(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const title =
        document.querySelector("h1")?.innerText?.trim() ||
        document.title?.trim() ||
        "Untitled";

      const articleEl = document.querySelector("article");
      const mainEl = document.querySelector('[role="main"]');
      const node = articleEl || mainEl || document.body;

      let content = "";
      if (node) {
        content = (node.innerText || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 4000);
      }

      // NEW: count links inside main/article (category pages usually have many)
      const container = articleEl || mainEl || document.body;
      const linkCount = container ? container.querySelectorAll("a").length : 0;

      return { title, content, linkCount };
    },
  });

  return results?.[0]?.result || { title: "", content: "", linkCount: 0 };
}


// ---------- API ----------

async function sendArticle(article) {
  const response = await fetch(`${API_BASE_URL}/article`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(article),
  });

  if (!response.ok) {
    const txt = await response.text().catch(() => "");
    throw new Error(`SeenIt API error: ${response.status} ${txt}`);
  }

  return await response.json();
}

// ---------- Storage: clusters (for popup) ----------

function upsertClusters(article, result) {
  chrome.storage.local.get(["clusters"], (res) => {
    const clusters = res.clusters || {};

    const clusterId = result?.cluster_id || article.url; // fallback
    const cluster =
      clusters[clusterId] || {
        representativeTitle: article.title,
        articles: [],
        lastVisited: article.timestamp,
      };

    // keep representative title fresh
    if (!cluster.representativeTitle) cluster.representativeTitle = article.title;

    // helper to avoid duplicates
    const add = (title, url, similarity) => {
      if (!url) return;
      if (!cluster.articles.some((a) => a.url === url)) {
        cluster.articles.push({ title: title || "Untitled", url, similarity });
      }
    };

    cluster.currentUrl = article.url;
    cluster.currentTitle = article.title;

    // include matches returned by API
    (result?.matches || []).forEach((m) => {
      add(m.title, m.url, m.similarity);
    });

    cluster.lastVisited = article.timestamp;
    clusters[clusterId] = cluster;

    chrome.storage.local.set({ clusters }, () => {
      if (chrome.runtime.lastError) {
        console.error("SeenIt: storage error:", chrome.runtime.lastError);
      } else {
        console.log("SeenIt: clusters saved", { clusterId, count: cluster.articles.length });
      }
    });
  });
}

// ---------- Core Logic ----------

async function processTab(tabId, tab) {
  if (!tab?.url || !isTrackedSite(tab.url)) return;

  try {
    const extracted = await extractArticle(tabId);
    
    // NEW: skip category/section pages (too many links)
    if ((extracted.linkCount || 0) > 120) {
    console.log("SeenIt: skipped likely category page (too many links)", extracted.linkCount, tab.url);
    return;
    }
    if (!extracted.title || !extracted.content) {
      console.log("SeenIt: No article content extracted");
      return;
    }

    const article = {
      title: extracted.title,
      content: extracted.content,
      url: tab.url,
      domain: new URL(tab.url).hostname.replace("www.", ""),
      timestamp: new Date().toISOString(),
    };

    console.log("SeenIt: sending article", article.url);

    const result = await sendArticle(article);

    // Save for popup
    upsertClusters(article, result);

    // If you have a content-script that shows banner
    if (result?.similar_found) {
      chrome.tabs.sendMessage(tabId, {
        type: "SHOW_SEENIT_BANNER",
        matches: result.matches || [],
      }).catch(() => {
        // if no content script on this page, ignore
      });
    }

    console.log("SeenIt: processed OK", { url: article.url, cluster: result?.cluster_id });
  } catch (err) {
    console.error("SeenIt error:", err);
  }
}

// ---------- SPA-safe listeners ----------

// Full page load
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete") {
    processTab(tabId, tab);
  }
});

// Switching tabs (often triggers SPA navigation as well)
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    processTab(tabId, tab);
  } catch (e) {
    // ignore
  }
});

console.log("SeenIt: background script loaded");
