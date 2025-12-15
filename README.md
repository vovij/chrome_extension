# SeenIt - Minimal Barebone Extension

**Total: ~170 lines of code** - No frameworks, no auth, just pure HTML/CSS/JS.

## What's Included

- ✅ 3 tabs: Current Page, List, Settings
- ✅ Mark page as seen
- ✅ Mark page & hide similar (auto-close)
- ✅ View seen list
- ✅ Auto-close toggle
- ✅ Chrome local storage (no backend needed)
- ✅ Background service worker for auto-close

## File Structure

```
minimal-extension/
├── manifest.json       # Extension config
├── popup.html         # Main UI (~80 lines)
├── popup.js           # Logic (~70 lines)
└── background.js      # Auto-close (~15 lines)
```

## Setup (2 minutes)

1. **Add Icons** (required):
   - Create or download 3 PNG files: `icon16.png`, `icon48.png`, `icon128.png`
   - Put them in the `minimal-extension/` folder

2. **Load in Chrome**:
   - Open `chrome://extensions/`
   - Enable "Developer mode"
   - Click "Load unpacked"
   - Select the `minimal-extension/` folder

3. **Done!** Click the extension icon to use it.

## How It Works

### Data Storage
Uses `chrome.storage.local` - no database needed:
```javascript
{
  seenItems: [
    {
      id: timestamp,
      url: "https://example.com",
      title: "Page Title",
      timestamp: "2025-12-15T...",
      hideSimilar: true/false
    }
  ],
  autoClose: true/false
}
```

### Features

**Current Page Tab**:
- Shows current page info
- "Mark as Seen" button - saves to storage
- "Mark & Hide Similar" - saves + enables auto-close for this URL

**List Tab**:
- Displays all seen pages
- Shows date and auto-close status

**Settings Tab**:
- Toggle auto-close feature on/off

**Background Worker**:
- Monitors tab updates
- Auto-closes tabs if URL matches a "hide similar" entry

## Extending This

Add these features by editing the files:

### 1. Delete from List
In `popup.js`, add delete buttons:
```javascript
// In loadSeenList(), add to HTML:
<button onclick="deleteItem(${item.id})">Delete</button>

// Add function:
function deleteItem(id) {
  chrome.storage.local.get(['seenItems'], (result) => {
    const items = result.seenItems.filter(item => item.id !== id);
    chrome.storage.local.set({ seenItems: items }, loadSeenList);
  });
}
```

### 2. Search
Add an input in `popup.html`:
```html
<input type="text" id="search" placeholder="Search...">
```

Filter in `popup.js`:
```javascript
document.getElementById('search').addEventListener('input', (e) => {
  const query = e.target.value.toLowerCase();
  // Filter seenItems by title/url containing query
});
```

### 3. Tags/Categories
Add to data structure:
```javascript
{
  ...item,
  tags: ['work', 'research']
}
```

### 4. Export Data
```javascript
function exportData() {
  chrome.storage.local.get(['seenItems'], (result) => {
    const json = JSON.stringify(result.seenItems, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    chrome.downloads.download({ url, filename: 'seenit-export.json' });
  });
}
```

### 5. Add Backend (Supabase/Firebase)
Replace `chrome.storage.local` calls with API calls:
```javascript
// Instead of:
chrome.storage.local.set({ seenItems }, callback);

// Use:
await fetch('https://your-api.com/seen', {
  method: 'POST',
  body: JSON.stringify(item)
});
```

## Total Code Size

- `popup.html`: ~80 lines (structure + inline styles)
- `popup.js`: ~70 lines (all logic)
- `background.js`: ~15 lines (auto-close)
- `manifest.json`: ~25 lines (config)

**Total: ~190 lines**

## Quick Icon Solution

Use emoji icons from [favicon.io](https://favicon.io/emoji-favicons/):
1. Search "eye" emoji
2. Download
3. Rename files to `icon16.png`, `icon48.png`, `icon128.png`
4. Copy to extension folder

Or create temporary placeholders:
```bash
# macOS/Linux with ImageMagick
convert -size 16x16 xc:blue icon16.png
convert -size 48x48 xc:blue icon48.png
convert -size 128x128 xc:blue icon128.png
```

## That's It!

This is the absolute minimum viable Chrome extension for content tracking. No dependencies, no build step, no auth - just load and use.

Start here, then add whatever features you need!
