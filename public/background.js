chrome.runtime.onInstalled.addListener(() => {
  console.log('SeenIt extension installed');
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    chrome.storage.local.get(['autoClose', 'seenUrls'], (result) => {
      const seenUrls = result.seenUrls || [];
      const autoClose = result.autoClose || false;

      if (autoClose && seenUrls.includes(tab.url)) {
        chrome.tabs.remove(tabId);
      }
    });
  }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getCurrentTab') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        sendResponse({
          url: tabs[0].url,
          title: tabs[0].title,
          favicon: tabs[0].favIconUrl
        });
      }
    });
    return true;
  }
});
