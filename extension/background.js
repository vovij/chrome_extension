// background.js — SeenIt (MV3)

const API_BASE_URL = "https://seenit.doc.ic.ac.uk";

const TRACKED_SITES = [
  "bbc.co.uk",
  "reuters.com",
  "cnn.com",
  "nytimes.com",
  "theguardian.com",
];


// utils

function isTrackedSite(url) {
  try {
    const hostname = new URL(url).hostname.replace("www.", "");
    return TRACKED_SITES.some((site) => hostname.includes(site));
  } catch {
    return false;
  }
}

async function getAuthToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["token"], (result) => {
      resolve(result.token || null);
    });
  });
}

function normalizeUrl(raw) {
  try {
    const u = new URL(raw);
    u.hash = "";
    u.hostname = u.hostname.toLowerCase().replace(/^www\./, "");
    u.protocol = (u.protocol || "https:").toLowerCase();

    if (u.pathname.length > 1 && u.pathname.endsWith("/")) {
      u.pathname = u.pathname.slice(0, -1);
    }

    const dropKeys = new Set([
      "ref", "cmpid", "ocid", "taid", "rpc",
      "at_medium", "at_campaign", "at_link_id", "at_link_type",
      "at_link_origin", "at_format", "at_ptr_name", "at_bbc_team",
      "fbclid", "gclid", "gbraid", "wbraid",
      "mc_cid", "mc_eid",
    ]);

    for (const key of Array.from(u.searchParams.keys())) {
      const k = key.toLowerCase();
      if (k.startsWith("utm_") || k.startsWith("at_") || dropKeys.has(k)) {
        u.searchParams.delete(key);
      }
    }

    u.search = u.searchParams.toString() ? `?${u.searchParams.toString()}` : "";
    return u.toString();
  } catch {
    return raw;
  }
}

async function handleAuthError() {
  await chrome.storage.local.remove(["user", "token"]);
  console.log("[SeenIt] auth token cleared, user must re-login");
}


// article extraction

async function extractArticle(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const title =
        document.querySelector("h1")?.innerText?.trim() ||
        document.title?.trim() ||
        "Untitled";

      // try selectors from most specific to broadest
      const selectors = [
        "article",
        "main article",
        "[itemprop='articleBody']",
        ".article__body",
        ".story-body__inner",
        ".article-body",
        ".post-content",
        ".entry-content",
        "[data-component='article-body']",
        "main",
      ];

      let node = null;
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
          const text = (el.innerText || "").replace(/\s+/g, " ").trim();
          if (text.length >= 100) {
            node = el;
            break;
          }
        }
      }
      if (!node) node = document.body;

      // body fallback: if content is too large, let the server extract it instead
      if (node === document.body) {
        const bodyText = (node.innerText || "").replace(/\s+/g, " ").trim();
        if (bodyText.length > 8000) {
          node = null;
        }
      }

      const content = node
        ? (node.innerText || "").replace(/\s+/g, " ").trim().slice(0, 4000)
        : "";

      const linkCount = node ? node.querySelectorAll("a").length : 0;

      return { title, content, linkCount };
    },
  });

  return results?.[0]?.result || { title: "", content: "", linkCount: 0 };
}


// API

// shared fetch helper to avoid duplicating auth/error logic
async function apiRequest(path, body) {
  const token = await getAuthToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (response.status === 401 || response.status === 403) {
    await handleAuthError();
    throw new Error("Not authenticated");
  }

  if (!response.ok) {
    const txt = await response.text().catch(() => "");
    throw new Error(`SeenIt API error ${response.status}: ${txt}`);
  }

  return response.json();
}

const sendArticle = (article) => apiRequest("/article", article);
const sendURL = (url) => apiRequest("/extract-url", { url });

async function syncClustersFromBackend() {
  const token = await getAuthToken();
  if (!token) return;

  const response = await fetch(`${API_BASE_URL}/api/history`, {
    headers: { "Authorization": `Bearer ${token}` },
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      await handleAuthError();
      return;
    }
    const txt = await response.text().catch(() => "");
    throw new Error(`SeenIt history sync error ${response.status}: ${txt}`);
  }

  const data = await response.json();
  await chrome.storage.local.set({ clusters: data?.clusters || {} });
}


// core logic

async function processTab(tabId, tab) {
  if (!tab?.url || !isTrackedSite(tab.url)) return;

  const token = await getAuthToken();
  if (!token) {
    console.log("[SeenIt] user not authenticated, skipping");
    return;
  }

  const normUrl = normalizeUrl(tab.url);

  try {
    const result = await chrome.storage.local.get(["recentlyProcessed"]);
    const recentlyProcessed = result.recentlyProcessed || {};
    const now = Date.now();

    // skip if processed within the last 5 minutes
    if (recentlyProcessed[normUrl] && now - recentlyProcessed[normUrl] < 5 * 60 * 1000) {
      console.log("[SeenIt] skipping recently processed tab", normUrl);
      return;
    }

    const extracted = await extractArticle(tabId);

    // skip category/section pages with too many links
    if ((extracted.linkCount || 0) > 120) {
      console.log("[SeenIt] skipped likely category page", normUrl);
      return;
    }

    let apiResult;

    if (extracted.title && extracted.content && extracted.content.length > 200) {
      // local extraction succeeded — send content directly
      console.log("[SeenIt] using local extraction");
      apiResult = await sendArticle({
        title: extracted.title,
        content: extracted.content,
        url: normUrl,
        domain: new URL(normUrl).hostname.replace("www.", ""),
        timestamp: new Date().toISOString(),
      });
    } else {
      // local extraction failed — fall back to server-side extraction
      console.log("[SeenIt] falling back to server-side extraction", extracted);
      apiResult = await sendURL(normUrl);
    }

    // update the recently-processed cache and evict entries older than 1 hour
    recentlyProcessed[normUrl] = now;
    for (const url of Object.keys(recentlyProcessed)) {
      if (now - recentlyProcessed[url] > 60 * 60 * 1000) delete recentlyProcessed[url];
    }
    chrome.storage.local.set({ recentlyProcessed });

    if (apiResult) {
      await syncClustersFromBackend();

      if (apiResult.similar_found) {
        chrome.tabs.sendMessage(tabId, {
          type: "SHOW_SEENIT_BANNER",
          matches: apiResult.matches || [],
          novelty: apiResult.novelty || null,
          noveltyDetails: apiResult.novelty_details || null,
        }).catch(() => {}); // ignore if no content script on this page
      }

      console.log("[SeenIt] processed OK", {
        url: tab.url,
        cluster: apiResult.cluster_id,
        matches: apiResult.matches?.length || 0,
        method: extracted.content?.length > 200 ? "local" : "server",
      });
    }

  } catch (err) {
    console.error("[SeenIt] error:", err);
    chrome.notifications?.create({
      type: "basic",
      iconUrl: "icon.png",
      title: "SeenIt Error",
      message: err.message === "Not authenticated"
        ? "Please login to track articles"
        : "Failed to process article",
    }).catch(() => {});
  }
}


// listeners

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete") processTab(tabId, tab);
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    processTab(tabId, tab);
  } catch {
    // tab may have closed before we could read it
  }
});

console.log("[SeenIt] background script loaded");