// Get the list of tracked sites from background.js
const TRACKED_SITES = [
  'bbc.co.uk',
  'reuters.com'
];

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
    
    // If switching to settings, load stats
    if (targetTab === 'settings') {
      loadStats();
    }
  });
});

// Get current tab info
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const currentTab = tabs[0];
  if (currentTab) {
    document.querySelector('.page-title').textContent = currentTab.title;
    document.querySelector('.page-url').textContent = currentTab.url;
    
    // Check if current page is being tracked
    if (isTrackedSite(currentTab.url)) {
      document.getElementById('tracking-status').style.display = 'block';
    }
  }
});

// Check if URL matches any tracked site
function isTrackedSite(url) {
  try {
    const hostname = new URL(url).hostname.replace('www.', '');
    return TRACKED_SITES.some(site => hostname.includes(site));
  } catch {
    return false;
  }
}

// Load seen list
function loadSeenList() {
  chrome.storage.local.get(['seenItems'], (result) => {
    const seenItems = result.seenItems || [];
    const listContainer = document.getElementById('seen-list');
    
    if (seenItems.length === 0) {
      listContainer.innerHTML = '<p style="color: #6b7280;">No items yet</p>';
      return;
    }
    
    // Sort by timestamp (newest first)
    const sortedItems = [...seenItems].sort((a, b) => 
      new Date(b.timestamp) - new Date(a.timestamp)
    );
    
    listContainer.innerHTML = sortedItems.map(item => `
      <div class="list-item">
        <div style="font-weight: 500; margin-bottom: 4px;">${item.title}</div>
        <div style="font-size: 12px; color: #6b7280;">
          ${item.domain} • ${new Date(item.timestamp).toLocaleDateString()}
        </div>
      </div>
    `).join('');
  });
}

// Load tracked sites in settings
function loadTrackedSites() {
  const container = document.getElementById('tracked-sites');
  container.innerHTML = TRACKED_SITES.map(site => `
    <div class="tracked-site">
      ✓ ${site}
    </div>
  `).join('');
}

// Load statistics
function loadStats() {
  chrome.storage.local.get(['seenItems'], (result) => {
    const seenItems = result.seenItems || [];
    
    // Total count
    document.getElementById('total-tracked').textContent = seenItems.length;
    
    // Today's count
    const today = new Date().toDateString();
    const todayCount = seenItems.filter(item => 
      new Date(item.timestamp).toDateString() === today
    ).length;
    document.getElementById('today-tracked').textContent = todayCount;
  });
}

// Clear all history
document.getElementById('clear-all').addEventListener('click', () => {
  if (confirm('Clear all tracking history?')) {
    chrome.storage.local.set({ seenItems: [] }, () => {
      loadSeenList();
      loadStats();
    });
  }
});

// Load list on init
loadSeenList();
loadTrackedSites();
loadStats();

// Refresh list every 3 seconds
setInterval(() => {
  const listTab = document.getElementById('list');
  if (listTab.classList.contains('active')) {
    loadSeenList();
  }
}, 3000);