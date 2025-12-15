# Quick Start Guide

Get SeenIt running in 5 minutes!

## Step 1: Setup Supabase (2 minutes)

1. Go to [https://supabase.com](https://supabase.com)
2. Click "Start your project" and sign up (it's free)
3. Click "New project"
   - Choose organization
   - Name: "seenit" (or anything you like)
   - Database Password: (create a strong password)
   - Region: (choose closest to you)
   - Click "Create new project"
4. Wait 1-2 minutes for project to be ready

## Step 2: Get API Credentials (1 minute)

1. In your Supabase project dashboard:
   - Click "Settings" (gear icon) in the sidebar
   - Click "API" under Project Settings
2. Copy these two values:
   - **Project URL** (looks like: `https://xxxxx.supabase.co`)
   - **anon/public key** (long string starting with `eyJ...`)

## Step 3: Configure Extension (1 minute)

1. In your project folder, create a `.env` file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and paste your credentials:
   ```
   VITE_SUPABASE_URL=https://your-project.supabase.co
   VITE_SUPABASE_ANON_KEY=eyJhbGc...your-key-here
   ```

## Step 4: Build Extension (1 minute)

```bash
npm install
chmod +x scripts/build-extension.sh
./scripts/build-extension.sh
```

## Step 5: Add Icons (30 seconds)

You need 3 icon files in the `dist/` folder. Quick options:

### Option A: Use Emoji Icons (Fastest)
1. Go to [https://favicon.io/emoji-favicons/](https://favicon.io/emoji-favicons/)
2. Search for "eye" emoji
3. Download the ZIP
4. Extract and copy these files to `dist/`:
   - `favicon-16x16.png` → rename to `icon16.png`
   - Copy to `icon48.png` (same file)
   - Copy to `icon128.png` (same file)

### Option B: Create Simple Icons
Create three PNG files (16x16, 48x48, 128x128) with any design tool or online icon maker.

### Option C: Temporary Solution
For testing, you can use any three PNG files temporarily. Just name them correctly.

## Step 6: Load in Chrome (30 seconds)

1. Open Chrome
2. Go to `chrome://extensions/`
3. Toggle "Developer mode" ON (top-right)
4. Click "Load unpacked"
5. Select the `dist/` folder from your project
6. Done!

## First Use

1. Click the SeenIt icon in your Chrome toolbar
2. Sign up with email and password
3. Browse to any webpage
4. Click the extension icon
5. Click "Mark as Seen"

That's it! You're now tracking your seen content.

## Troubleshooting

### "Failed to load extension"
- Make sure you selected the `dist/` folder, not the project root
- Verify `manifest.json` exists in `dist/`

### "Supabase errors"
- Double-check your `.env` file has correct URL and key
- Make sure there are no spaces around the `=` signs
- Rebuild: `./scripts/build-extension.sh`

### "Cannot read properties..."
- Make sure icons are in `dist/` folder
- Icons must be named exactly: `icon16.png`, `icon48.png`, `icon128.png`

### Need Help?
Check the full README.md or DEVELOPMENT.md for detailed information.
