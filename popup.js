// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const targetTab = tab.dataset.tab;
    
    // Update tabs
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    
    // Update content
    document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
    document.getElementById(targetTab).classList.add('active');
  });
});

// Get current tab info
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const currentTab = tabs[0];
  if (currentTab) {
    document.querySelector('.page-title').textContent = currentTab.title;
    document.querySelector('.page-url').textContent = currentTab.url;
  }
});

// Mark as seen
document.getElementById('mark-seen').addEventListener('click', () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    
    // Get existing seen items
    chrome.storage.local.get(['seenItems'], (result) => {
      const seenItems = result.seenItems || [];
      
      // Add new item
      seenItems.push({
        id: Date.now(),
        url: tab.url,
        title: tab.title,
        timestamp: new Date().toISOString(),
        hideSimilar: false
      });
      
      // Save
      chrome.storage.local.set({ seenItems }, () => {
        alert('Page marked as seen!');
        loadSeenList();
      });
    });
  });
});

// Mark and hide similar
document.getElementById('mark-hide').addEventListener('click', () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    
    chrome.storage.local.get(['seenItems'], (result) => {
      const seenItems = result.seenItems || [];
      
      seenItems.push({
        id: Date.now(),
        url: tab.url,
        title: tab.title,
        timestamp: new Date().toISOString(),
        hideSimilar: true
      });
      
      chrome.storage.local.set({ seenItems }, () => {
        alert('Page marked! Similar pages will be auto-closed.');
        loadSeenList();
      });
    });
  });
});

// Load seen list
function loadSeenList() {
  chrome.storage.local.get(['seenItems'], (result) => {
    const seenItems = result.seenItems || [];
    const listContainer = document.getElementById('seen-list');
    
    if (seenItems.length === 0) {
      listContainer.innerHTML = '<p style="color: #6b7280;">No items yet</p>';
      return;
    }
    
    listContainer.innerHTML = seenItems.map(item => `
      <div class="list-item">
        <div style="font-weight: 500; margin-bottom: 4px;">${item.title}</div>
        <div style="font-size: 12px; color: #6b7280;">${new Date(item.timestamp).toLocaleDateString()}</div>
        ${item.hideSimilar ? '<div style="font-size: 11px; color: #f59e0b; margin-top: 4px;">🔒 Auto-close enabled</div>' : ''}
      </div>
    `).join('');
  });
}

// Auto-close setting
document.getElementById('auto-close').addEventListener('change', (e) => {
  chrome.storage.local.set({ autoClose: e.target.checked });
});

// Load auto-close setting
chrome.storage.local.get(['autoClose'], (result) => {
  document.getElementById('auto-close').checked = result.autoClose || false;
});

// Load list on init
loadSeenList();
