# SeenIt - Content Similarity Identifier

A Chrome extension that helps you track web content you've already seen, saving you time while browsing.

## Features

- **Track Seen Content**: Mark web pages you've already read
- **Auto-Close Similar Content**: Automatically close tabs with content you've marked to hide
- **Sync Across Devices**: Uses Supabase for cloud storage
- **Simple Interface**: Clean, intuitive popup interface
- **Privacy-Focused**: Your data is encrypted and only accessible to you

## Setup Instructions

### Prerequisites

1. Node.js (v18 or higher)
2. A Supabase account (free tier works fine)

### 1. Configure Supabase

1. Go to [Supabase](https://supabase.com) and create a new project
2. Once your project is ready, go to Project Settings > API
3. Copy your project URL and anon/public key
4. Create a `.env` file in the project root:

```env
VITE_SUPABASE_URL=your_supabase_project_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Build the Extension

```bash
npm run build
```

This will create a `dist` folder with your extension files.

### 4. Load Extension in Chrome

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (toggle in top-right corner)
3. Click "Load unpacked"
4. Select the `dist` folder from this project
5. The SeenIt extension should now appear in your extensions list

### 5. Copy Required Files

After building, you need to copy these files to the `dist` folder:

```bash
cp public/manifest.json dist/
cp public/background.js dist/
```

You'll also need to add extension icons. You can:
- Create your own 16x16, 48x48, and 128x128 PNG icons
- Use a free icon generator
- Save them as `icon16.png`, `icon48.png`, `icon128.png` in the `dist` folder

## Usage

1. **Sign Up/Sign In**: Create an account or sign in when you first open the extension
2. **Mark Pages as Seen**:
   - Click the extension icon while on any webpage
   - Click "Mark as Seen" to track the page
   - Click "Mark as Seen & Hide Similar" to auto-close similar content
3. **View Seen Content**: Check the "Seen List" tab to see all tracked pages
4. **Configure Settings**: Enable auto-close in the Settings tab

## Development

### Run in Development Mode

For development with hot reload:

```bash
npm run dev
```

Note: For Chrome extension development, you'll need to rebuild and reload the extension in Chrome after changes.

### Project Structure

```
src/
├── components/          # React components
│   ├── Auth.tsx        # Login/signup interface
│   ├── Header.tsx      # Extension header
│   ├── CurrentPage.tsx # Current page tracker
│   ├── SeenList.tsx    # List of seen content
│   └── Settings.tsx    # Extension settings
├── lib/
│   └── supabase.ts     # Supabase client configuration
├── types/
│   └── index.ts        # TypeScript type definitions
├── App.tsx             # Main application component
└── main.tsx            # Application entry point
```

## Future Enhancements

The current version is a minimal viable product (MVP). Future enhancements could include:

1. **Content Similarity Detection**: Use NLP and semantic analysis to detect similar articles
2. **Smart Categorization**: Automatically categorize content by topic
3. **Content Clustering**: Group similar articles together like Google News
4. **Export/Import**: Export your seen content data
5. **Statistics**: View browsing statistics and patterns
6. **Bulk Actions**: Mark multiple pages at once
7. **Search**: Search through your seen content
8. **Tags**: Add custom tags to organize content

## Publishing to Chrome Web Store

To publish this extension:

1. **Prepare for Production**:
   - Ensure all features work correctly
   - Test thoroughly in different scenarios
   - Add proper extension icons
   - Write a compelling description

2. **Create a ZIP file**:
   ```bash
   npm run build
   cp public/manifest.json dist/
   cp public/background.js dist/
   cd dist
   zip -r seenit-extension.zip .
   ```

3. **Submit to Chrome Web Store**:
   - Go to [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole)
   - Pay one-time $5 registration fee (if not already registered)
   - Click "New Item"
   - Upload your ZIP file
   - Fill in store listing information:
     - Detailed description
     - Screenshots (1280x800 or 640x400)
     - Small tile icon (440x280)
     - Category and language
   - Set pricing and distribution
   - Submit for review

4. **Review Process**:
   - Chrome will review your extension (usually takes a few days)
   - You'll be notified via email about approval or any required changes

## Technical Details

### Technologies Used

- **React 18** with TypeScript
- **Vite** for building
- **Tailwind CSS** for styling
- **Supabase** for authentication and database
- **Lucide React** for icons
- **Chrome Extension Manifest V3**

### Database Schema

The extension uses a single `seen_content` table:
- Stores URL, title, favicon
- Tracks when content was first seen
- Supports "hide similar" flag for auto-closing
- Row Level Security ensures privacy

### Chrome APIs Used

- `chrome.tabs`: Get current tab information
- `chrome.storage.local`: Store settings locally
- `chrome.runtime`: Message passing between popup and background
- `chrome.action`: Extension popup

## License

MIT License - Feel free to use and modify for your needs.

## Contributing

This is a minimal frontend implementation. Contributions welcome for:
- NLP/content similarity features
- UI/UX improvements
- Bug fixes
- Documentation

## Support

For issues or questions, please open an issue on GitHub.
