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

## Setup

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

## How It Works

1. Visit BBC, Reuters, Guardian, NYT, or CNN article
2. Extension auto-tracks it in the background
3. Data saved locally (Chrome storage) + synced to backend API
4. Click extension icon to see your history

## Tracked Sites

Currently tracking:
- `bbc.co.uk`
- `reuters.com`
- `theguardian.com`
- `nytimes.com`
- `cnn.com`

To add more: Edit `TRACKED_SITES` in `extension/background.js`

## Backend

The backend handles:
- **Article storage** - Saves tracked articles with metadata
- **User management** - Auto-generated user IDs for tracking
- **Similarity detection** - NLP and content analysis will be implemented here
- **API endpoints** - REST API for extension communication

### Current API Endpoints

- `POST /api/articles` - Save article
- `GET /api/articles/:userId` - Get user's articles
- `POST /api/similarity/check` - Check if similar article exists
- `DELETE /api/articles/:id` - Delete article
- `DELETE /api/articles/user/:userId` - Clear user history

### Data Storage

**Backend** (in-memory for now):
- Article URL, title, timestamp
- User ID (auto-generated)
- Domain

**Extension** (Chrome local storage):
- Same data as backend
- Works offline

### NLP & Similarity Detection

The backend will implement:
- **Text embeddings** - Convert article content to vector representations
- **Semantic similarity** - Compare articles using cosine similarity
- **Content extraction** - Scrape and parse article text
- **Clustering** - Group similar articles together
- **Topic detection** - Identify article subjects automatically