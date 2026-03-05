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

// NEW: Get auth token from storage
async function getAuthToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['token'], (result) => {
      resolve(result.token || null);
    });
  });
}

function normalizeUrl(raw) {
  try {
    const u = new URL(raw);
    u.hash = "";

    // Normalize hostname
    u.hostname = u.hostname.toLowerCase().replace(/^www\./, "");
    u.protocol = (u.protocol || "https:").toLowerCase();

    // Trim trailing slash (except root)
    if (u.pathname.length > 1 && u.pathname.endsWith("/")) {
      u.pathname = u.pathname.slice(0, -1);
    }

    // Drop tracking params (expanded)
    const dropKeys = new Set([
      "ref", "cmpid", "ocid", "taid", "rpc",
      // BBC / common publisher tracking
      "at_medium", "at_campaign", "at_link_id", "at_link_type",
      "at_link_origin", "at_format", "at_ptr_name", "at_bbc_team",
      // common ad/click ids
      "fbclid", "gclid", "gbraid", "wbraid",
      // common newsletter params
      "mc_cid", "mc_eid",
    ]);

    for (const key of Array.from(u.searchParams.keys())) {
      const k = key.toLowerCase();
      if (k.startsWith("utm_") || k.startsWith("at_") || dropKeys.has(k)) {
        u.searchParams.delete(key);
      }
    }

    // Rebuild query
    u.search = u.searchParams.toString() ? `?${u.searchParams.toString()}` : "";
    return u.toString();
  } catch {
    return raw;
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
  const token = await getAuthToken();
  
  if (!token) {
    console.error("SeenIt: No auth token found. User must login.");
    throw new Error("Not authenticated");
  }

  const response = await fetch(`${API_BASE_URL}/article`, {
    method: "POST",
    headers: { 
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`  // NEW: Send auth token
    },
    body: JSON.stringify(article),
  });

  if (!response.ok) {
    const txt = await response.text().catch(() => "");
    throw new Error(`SeenIt API error: ${response.status} ${txt}`);
  }

  return await response.json();
}

// NEW: Send URL for automatic extraction and processing
async function sendURL(url) {
  const token = await getAuthToken();
  
  if (!token) {
    console.error("SeenIt: No auth token found. User must login.");
    throw new Error("Not authenticated");
  }

  const response = await fetch(`${API_BASE_URL}/extract-url`, {
    method: "POST", 
    headers: { 
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`  // NEW: Send auth token
    },
    body: JSON.stringify({ url }),
  });

  if (!response.ok) {
    const txt = await response.text().catch(() => "");
    throw new Error(`SeenIt URL API error: ${response.status} ${txt}`);
  }

  return await response.json();
}

// ---------- Storage: clusters (for popup) ----------
function upsertClusters(article, result) {
  chrome.storage.local.get(["clusters"], (res) => {
    const clusters = res.clusters || {};

    const clusterIdRaw = result?.cluster_id || article.url;
    const clusterId = normalizeUrl(clusterIdRaw);

    // Create target cluster if missing.
    // IMPORTANT: representative stays FIRST seen
    const target = clusters[clusterId] || {
      representativeTitle: article.title,
      representativeUrl: article.url,
      articles: [],
      lastVisited: article.timestamp,
      currentUrl: article.url, // keep current separately
      currentTitle: article.title,
      currentSimilarity: null, // similarity of current page to representative (computed)
    };

    const repNorm = normalizeUrl(target.representativeUrl || article.url);
    const currentNorm = normalizeUrl(article.url);

    // Membership set used for overlap detection and the "one cluster per URL" rule.
    // Includes representative, current page, and all matched URLs.
    const memberUrls = new Set([repNorm, currentNorm]);
    (result?.matches || []).forEach((m) => {
      if (m?.url) memberUrls.add(normalizeUrl(m.url));
    });

    // Compute similarity of CURRENT page to REPRESENTATIVE (from real backend match)
    // If the current page IS the representative, it's trivially 1.0.
    let currentSimilarity = null;
    if (currentNorm === repNorm) {
      currentSimilarity = 1.0;
    } else {
      const repMatch = (result?.matches || []).find(
        (m) => m?.url && normalizeUrl(m.url) === repNorm
      );
      if (
        repMatch &&
        typeof repMatch.similarity === "number" &&
        Number.isFinite(repMatch.similarity)
      ) {
        currentSimilarity = repMatch.similarity;
      }
    }

    // Helper: add/update scored bullets in target.articles
    // Dedupe by normalized URL; keep max similarity.
    const add = (title, url, similarity) => {
      if (!url) return;
      const norm = normalizeUrl(url);

      // Never list representative or current page as a scored bullet
      if (norm === repNorm) return;
      if (norm === currentNorm) return;

      // Only accept REAL computed similarities
      if (typeof similarity !== "number" || !Number.isFinite(similarity)) return;

      const idx = target.articles.findIndex(
        (a) => a?.url && normalizeUrl(a.url) === norm
      );

      if (idx >= 0) {
        const prevSim = target.articles[idx].similarity;
        const nextSim =
          typeof prevSim === "number" && Number.isFinite(prevSim)
            ? Math.max(prevSim, similarity)
            : similarity;

        target.articles[idx] = {
          title: target.articles[idx].title || title || "Untitled",
          url: target.articles[idx].url || url,
          similarity: nextSim,
        };
      } else {
        target.articles.push({ title: title || "Untitled", url, similarity });
      }
    };

    // Merge overlapping clusters into target
    for (const [otherId, other] of Object.entries(clusters)) {
      const otherKey = normalizeUrl(otherId);
      if (otherKey === clusterId) continue;

      const otherRepNorm = other?.representativeUrl
        ? normalizeUrl(other.representativeUrl)
        : null;

      const otherCurrentNorm = other?.currentUrl
        ? normalizeUrl(other.currentUrl)
        : null;

      let overlaps = false;

      // Overlap via representative or currentUrl
      if (otherRepNorm && memberUrls.has(otherRepNorm)) overlaps = true;
      if (!overlaps && otherCurrentNorm && memberUrls.has(otherCurrentNorm)) overlaps = true;

      // Overlap via scored bullets
      if (!overlaps && Array.isArray(other?.articles)) {
        overlaps = other.articles.some(
          (a) => a?.url && memberUrls.has(normalizeUrl(a.url))
        );
      }

      if (!overlaps) continue;

      // Pull scored bullets over using add() (dedupe + max similarity)
      (other.articles || []).forEach((a) => {
        add(a.title || "Untitled", a.url, a.similarity);
        if (a?.url) memberUrls.add(normalizeUrl(a.url));
      });

      // Treat other rep/current as members too (helps stripping later)
      if (otherRepNorm) memberUrls.add(otherRepNorm);
      if (otherCurrentNorm) memberUrls.add(otherCurrentNorm);

      // DO NOT replace representative (we keep first seen)
      delete clusters[otherId];
    }

    // Update current page fields (like background_old) + its computed similarity-to-rep
    target.currentUrl = article.url;
    target.currentTitle = article.title;
    target.currentSimilarity = currentSimilarity;
    target.lastVisited = article.timestamp;

    // Add new scored matches from API (rep/current are filtered out by add())
    (result?.matches || []).forEach((m) => add(m.title, m.url, m.similarity));

    // HARD INVARIANT: a URL may appear in only one cluster
    for (const [otherId, other] of Object.entries(clusters)) {
      const otherKey = normalizeUrl(otherId);
      if (otherKey === clusterId) continue;

      // Strip bullets
      if (Array.isArray(other?.articles)) {
        other.articles = other.articles.filter(
          (a) => a?.url && !memberUrls.has(normalizeUrl(a.url))
        );
      }

      // If other cluster's representative/current conflicts, or it has no bullets, delete it.
      const oRep = other?.representativeUrl ? normalizeUrl(other.representativeUrl) : null;
      const oCur = other?.currentUrl ? normalizeUrl(other.currentUrl) : null;

      const repConflicts = oRep && memberUrls.has(oRep);
      const curConflicts = oCur && memberUrls.has(oCur);
      const hasArticles = (other?.articles || []).length > 0;

      if (!hasArticles || repConflicts || curConflicts) delete clusters[otherId];
    }

    // Final dedupe pass (normalized URL)
    const seen = new Set();
    target.articles = target.articles.filter((a) => {
      if (!a?.url) return false;
      const k = normalizeUrl(a.url);
      if (!k) return false;
      if (k === repNorm) return false;
      if (k === currentNorm) return false;
      if (seen.has(k)) return false;
      seen.add(k);

      return typeof a.similarity === "number" && Number.isFinite(a.similarity);
    });

    // Store under normalized key
    // Extra safety: never allow representative URL into articles[]
    target.articles = (target.articles || []).filter(
      (a) => a?.url && normalizeUrl(a.url) !== repNorm
    );
      
    clusters[clusterId] = target;

    chrome.storage.local.set({ clusters }, () => {
      if (chrome.runtime.lastError) {
        console.error("SeenIt: storage error:", chrome.runtime.lastError);
      }
    });
  });
}

// ---------- Core Logic ----------

async function processTab(tabId, tab) {
    if (!tab?.url || !isTrackedSite(tab.url)) return;
    const normUrl = normalizeUrl(tab.url);

  // Check if user is authenticated
  const token = await getAuthToken();
  if (!token) {
    console.log("SeenIt: User not authenticated, skipping tracking");
    return;
  }

  try {
    console.log("SeenIt: processing tab", tab.url);
    
    const result = await chrome.storage.local.get(['recentlyProcessed']);
    const recentlyProcessed = result.recentlyProcessed || {};
    const now = Date.now();
    

    if (recentlyProcessed[normUrl] && (now - recentlyProcessed[normUrl]) < 5 * 60 * 1000) {
      console.log("SeenIt: article already processed recently, skipping", tab.url);
      return;
    }
    
    // Method 1: Try local extraction first (faster)
    const extracted = await extractArticle(tabId);
    
    // NEW: skip category/section pages (too many links)
    if ((extracted.linkCount || 0) > 120) {
      console.log("SeenIt: skipped likely category page (too many links)", extracted.linkCount, tab.url);
      return;
    }

    let apiResult = null;

    // Check if local extraction worked well
    if (extracted.title && extracted.content && extracted.content.length > 200) {
      // Use local extraction + send to API
      console.log("SeenIt: using local extraction");
      
      const article = {
        title: extracted.title,
        content: extracted.content,
        url: normUrl,
        domain: new URL(normUrl).hostname.replace("www.", ""),
        timestamp: new Date().toISOString(),
      };

      apiResult = await sendArticle(article);
      
    } else {
      // Fallback: Use server-side extraction
      console.log("SeenIt: local extraction failed, using server-side extraction");
      console.log("Local extraction result:", extracted);
      
      apiResult = await sendURL(normUrl);
    }

    recentlyProcessed[normUrl] = now;
    
    Object.keys(recentlyProcessed).forEach(url => {
      if (now - recentlyProcessed[url] > 60 * 60 * 1000) {
        delete recentlyProcessed[url];
      }
    });
    
    chrome.storage.local.set({ recentlyProcessed });

    // Save for popup and show banner
    if (apiResult) {
      let articleForStorage;
      
      if (extracted.title && extracted.content?.length > 200) {
        articleForStorage = {
          title: extracted.title,
          url: normUrl,
          domain: new URL(normUrl).hostname.replace("www.", ""),
          timestamp: new Date().toISOString(),
        };
      } else {
        //
        const extractedInfo = apiResult.extracted_article;
        articleForStorage = {
          title: extractedInfo?.title || `Article from ${new URL(normUrl).hostname}`,
          url: normUrl,
          domain: extractedInfo?.domain || new URL(normUrl).hostname.replace("www.", ""),
          timestamp: extractedInfo?.timestamp || new Date().toISOString(),
        };
      }

      upsertClusters(articleForStorage, apiResult);

      // Show banner if similar articles found
      if (apiResult?.similar_found) {
        chrome.tabs.sendMessage(tabId, {
          type: "SHOW_SEENIT_BANNER",
          matches: apiResult.matches || [],
	  novelty: apiResult.novelty || null,
	  noveltyDetails: apiResult.novelty_details || null,
        }).catch(() => {
          // if no content script on this page, ignore
        });
      }

      console.log("SeenIt: processed OK", { 
        url: tab.url, 
        cluster: apiResult?.cluster_id,
        method: extracted.content?.length > 200 ? "local" : "server",
        matches: apiResult?.matches?.length || 0,
        title: articleForStorage.title
      });
    }

  } catch (err) {
    console.error("SeenIt error:", err);
    
    // Show error notification (optional)
    chrome.notifications?.create({
      type: 'basic',
      iconUrl: 'icon.png',
      title: 'SeenIt Error', 
      message: err.message === 'Not authenticated' ? 'Please login to track articles' : 'Failed to process article'
    }).catch(() => {});
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
