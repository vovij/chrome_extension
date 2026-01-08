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
└── backend/               # Node.js API (Backend)
    ├── server.js          # Express server (all logic here)
    ├── package.json       # Dependencies
    └── .env               # Config
```

## Setup (5 minutes)

### 1. Backend

```bash
cd backend
npm install
npm start
```

Server runs on `http://localhost:3000`

### 2. Extension

1. Open Chrome and go to `chrome://extensions/`
2. Enable **"Developer mode"** (toggle in top right)
3. Click **"Load unpacked"**
4. Select the `extension/` folder
5. Done! ✅

### 3. Add Icons (Required)

The extension needs icons or it will error. Quick fix:

**Option A: Use Emoji Icons (2 minutes)**
1. Go to [favicon.io/emoji-favicons/](https://favicon.io/emoji-favicons/)
2. Search "eye" or "bookmark"
3. Download ZIP
4. Extract and rename files to:
   - `icon16.png`
   - `icon32.png`
   - `icon48.png`
   - `icon128.png`
5. Put them in `extension/icons/` folder

**Option B: Create Placeholders**
```bash
cd extension/icons
# Create simple blue squares (requires ImageMagick)
convert -size 16x16 xc:#3b82f6 icon16.png
convert -size 32x32 xc:#3b82f6 icon32.png
convert -size 48x48 xc:#3b82f6 icon48.png
convert -size 128x128 xc:#3b82f6 icon128.png
```

## How It Works

1. Visit BBC, Reuters, Guardian, NYT, or CNN article
2. Extension auto-tracks it in the background
3. Data saved locally (Chrome storage) + backend API
4. Click extension icon to see your history

## Tracked Sites

Currently tracking:
- `bbc.co.uk`
- `reuters.com`
- `theguardian.com`
- `nytimes.com`
- `cnn.com`

To add more: Edit `TRACKED_SITES` in `extension/background.js`

## What's Stored

**Backend** (in-memory for now):
- Article URL, title, timestamp
- User ID (auto-generated)
- Domain

**Extension** (Chrome local storage):
- Same data as backend
- Works offline

## API Endpoints

- `POST /api/articles` - Save article
- `GET /api/articles/:userId` - Get user's articles
- `POST /api/similarity/check` - Check if similar exists
- `DELETE /api/articles/:id` - Delete article

## Future Enhancements

- [ ] Add database (PostgreSQL/MongoDB)
- [ ] NLP-based similarity detection (embeddings)
- [ ] User authentication
- [ ] Cloud sync between devices
- [ ] Article content extraction

## Troubleshooting

**Extension error "ERR_FILE_NOT_FOUND"?**
- Add icons to `extension/icons/` folder (see step 3 above)
- Reload extension: `chrome://extensions/` → click refresh icon

**Backend not connecting?**
- Make sure backend is running: `npm start` in `backend/` folder
- Extension works offline, just won't sync to backend

**Extension not tracking?**
- Check you're on a tracked site (BBC, Reuters, etc.)
- Open Console: Right-click extension icon → Inspect popup → Console tab