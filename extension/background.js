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

    const clusterId = result?.cluster_id || article.url;
    const cluster = clusters[clusterId] || {
      representativeTitle: article.title,
      articles: [],
      lastVisited: article.timestamp,
    };

    // Keep representative title fresh
    if (!cluster.representativeTitle) cluster.representativeTitle = article.title;

    // Helper to avoid duplicates
    const add = (title, url, similarity = 0) => {
      if (!url) return;
      

      const existingIndex = cluster.articles.findIndex((a) => a.url === url);
      
      if (existingIndex >= 0) {
        if (similarity > (cluster.articles[existingIndex].similarity || 0)) {
          cluster.articles[existingIndex] = { 
            title: title || cluster.articles[existingIndex].title, 
            url, 
            similarity 
          };
        }
      } else {
        cluster.articles.push({ title: title || "Untitled", url, similarity });
      }
    };

    cluster.currentUrl = article.url;
    cluster.currentTitle = article.title;

    // Include ONLY matches returned by API (не текущую статью)
    (result?.matches || []).forEach((m) => {
      add(m.title, m.url, m.similarity);
    });

    cluster.lastVisited = article.timestamp;
    clusters[clusterId] = cluster;

    chrome.storage.local.set({ clusters }, () => {
      if (chrome.runtime.lastError) {
        console.error("SeenIt: storage error:", chrome.runtime.lastError);
      } else {
        console.log("SeenIt: clusters saved", { 
          clusterId, 
          count: cluster.articles.length,
          articlesInCluster: cluster.articles.map(a => a.title)
        });
      }
    });
  });
}

// ---------- Core Logic ----------

async function processTab(tabId, tab) {
  if (!tab?.url || !isTrackedSite(tab.url)) return;

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
    

    if (recentlyProcessed[tab.url] && (now - recentlyProcessed[tab.url]) < 5 * 60 * 1000) {
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
        url: tab.url,
        domain: new URL(tab.url).hostname.replace("www.", ""),
        timestamp: new Date().toISOString(),
      };

      apiResult = await sendArticle(article);
      
    } else {
      // Fallback: Use server-side extraction
      console.log("SeenIt: local extraction failed, using server-side extraction");
      console.log("Local extraction result:", extracted);
      
      apiResult = await sendURL(tab.url);
    }

    recentlyProcessed[tab.url] = now;
    
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
          url: tab.url,
          domain: new URL(tab.url).hostname.replace("www.", ""),
          timestamp: new Date().toISOString(),
        };
      } else {
        //
        const extractedInfo = apiResult.extracted_article;
        articleForStorage = {
          title: extractedInfo?.title || `Article from ${new URL(tab.url).hostname}`,
          url: tab.url,
          domain: extractedInfo?.domain || new URL(tab.url).hostname.replace("www.", ""),
          timestamp: extractedInfo?.timestamp || new Date().toISOString(),
        };
      }

      upsertClusters(articleForStorage, apiResult);

      // Show banner if similar articles found
      if (apiResult?.similar_found) {
        chrome.tabs.sendMessage(tabId, {
          type: "SHOW_SEENIT_BANNER",
          matches: apiResult.matches || [],
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