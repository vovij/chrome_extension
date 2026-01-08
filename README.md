# SeenIt - Auto News Tracker

Automatically track news articles you read. Minimal setup, 2 folders.

## Structure

```
seenit/
├── extension/              # Chrome Extension (Frontend)
│   ├── icons/             # Extension icons
│   ├── manifest.json      # Extension config
│   ├── popup.html         # UI
│   ├── popup.js           # UI logic
│   └── background.js      # Auto-tracking logic
│
└── backend/               # Backend with NLP logic (to be continued)
    ├── ...          
    ├── ...       
    └── ...               
```

## Setup

### 1. Extension

1. Open Chrome and go to `chrome://extensions/`
2. Enable **"Developer mode"** (toggle in top right)
3. Click **"Load unpacked"**
4. Select the `extension/` folder
5. Done! ✅

## How It Works

1. Visit BBC, Reuters (2 sites for now as demo)
2. Extension auto-tracks it in the background
3. Data saved locally (Chrome storage)
4. Click extension icon to see your history

## Tracked Sites

Currently tracking:
- `bbc.co.uk`
- `reuters.com`

To add more: Edit `TRACKED_SITES` in `extension/background.js`

### Data Storage

**Frontend (Extension)**:
- Uses Chrome's local storage API
- Stores article URL, title, timestamp, and domain
- Works offline - no backend required for basic tracking
- Data persists across browser sessions