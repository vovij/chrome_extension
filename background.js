// Listen for tab updates
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    chrome.storage.local.get(['autoClose', 'seenItems'], (result) => {
      if (!result.autoClose) return;
      
      const seenItems = result.seenItems || [];
      const matchingItem = seenItems.find(item => 
        item.url === tab.url && item.hideSimilar
      );
      
      if (matchingItem) {
        chrome.tabs.remove(tabId);
      }
    });
  }
});
