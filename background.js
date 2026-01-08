// Whitelist of news websites to monitor (starting with free sites)
const TRACKED_SITES = [
  'bbc.co.uk',
  'reuters.com'
];

// Check if URL matches any tracked site
function isTrackedSite(url) {
  try {
    const hostname = new URL(url).hostname.replace('www.', '');
    return TRACKED_SITES.some(site => hostname.includes(site));
  } catch {
    return false;
  }
}

// Listen for tab updates
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    
    // Only track if it's a whitelisted site
    if (isTrackedSite(tab.url)) {
      
      // Get existing seen items
      chrome.storage.local.get(['seenItems'], (result) => {
        const seenItems = result.seenItems || [];
        
        // Check if already seen (exact URL match to avoid duplicates)
        const alreadySeen = seenItems.some(item => item.url === tab.url);
        
        if (!alreadySeen) {
          // Add to seen list
          const newItem = {
            id: Date.now(),
            url: tab.url,
            title: tab.title || 'Untitled',
            timestamp: new Date().toISOString(),
            domain: new URL(tab.url).hostname.replace('www.', '')
          };
          
          seenItems.push(newItem);
          
          // Save back to storage
          chrome.storage.local.set({ seenItems }, () => {
            console.log('SeenIt: Tracked article -', newItem.title);
          });
        }
      });
    }
  }
});

// Make TRACKED_SITES available to popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getTrackedSites') {
    sendResponse({ sites: TRACKED_SITES });
  }
});