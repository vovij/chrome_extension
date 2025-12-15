# Development Guide for SeenIt

This guide will help you understand the codebase and develop new features for the SeenIt Chrome extension.

## Quick Start

1. **Clone and Setup**:
   ```bash
   npm install
   cp .env.example .env
   # Add your Supabase credentials to .env
   ```

2. **Build for Development**:
   ```bash
   chmod +x scripts/build-extension.sh
   ./scripts/build-extension.sh
   ```

3. **Load in Chrome**:
   - Open `chrome://extensions/`
   - Enable Developer mode
   - Load unpacked → select `dist/` folder

## Architecture Overview

### Frontend Structure

```
SeenIt Chrome Extension
│
├── Popup (React App)
│   ├── Authentication (Auth.tsx)
│   ├── Main Interface
│   │   ├── Current Page Tab
│   │   ├── Seen List Tab
│   │   └── Settings Tab
│   └── Header with Logout
│
└── Background Service Worker
    └── Tab monitoring & auto-close
```

### Data Flow

1. **User Authentication**:
   - Supabase Auth handles login/signup
   - Session stored and managed by Supabase client
   - Auth state synchronized across components

2. **Content Tracking**:
   - Extension reads current tab info via Chrome APIs
   - Checks against `seen_content` table in Supabase
   - Displays status (seen/unseen) to user
   - User can mark as seen with or without "hide similar" flag

3. **Auto-Close Feature**:
   - Background worker monitors tab updates
   - Checks URLs against seen content marked as "hide similar"
   - Automatically closes matching tabs if enabled in settings

## Key Components

### Auth.tsx
Handles user authentication (login/signup). Uses Supabase Auth.

**Key Functions**:
- `handleSubmit`: Processes login or signup
- Email/password validation
- Error handling and display

### CurrentPage.tsx
Main interface for checking and marking current page.

**Key Functions**:
- `loadCurrentTab`: Gets current tab info from Chrome
- `checkIfSeen`: Queries database for current URL
- `markAsSeen`: Saves current page to database
- `removeFromSeen`: Removes page from seen list

**Chrome API Usage**:
```typescript
chrome.runtime.sendMessage({ action: 'getCurrentTab' }, callback)
```

### SeenList.tsx
Displays list of all seen content with management options.

**Key Functions**:
- `loadSeenContent`: Fetches user's seen content from DB
- `removeItem`: Deletes item from seen list
- `openUrl`: Opens URL in new tab

### Settings.tsx
Extension settings management.

**Key Functions**:
- `handleAutoCloseChange`: Toggles auto-close feature
- Uses `chrome.storage.local` for settings persistence

### Background Service Worker (background.js)
Runs in background, monitors tabs, handles auto-close.

**Key Events**:
- `chrome.runtime.onInstalled`: Extension installation
- `chrome.tabs.onUpdated`: Tab navigation/refresh
- `chrome.runtime.onMessage`: Message passing from popup

## Database Schema

### seen_content Table

| Column | Type | Description |
|--------|------|-------------|
| id | uuid | Primary key |
| user_id | uuid | Foreign key to auth.users |
| url | text | Full webpage URL |
| title | text | Page title |
| content_hash | text | (Future) For similarity detection |
| favicon | text | Page favicon URL |
| seen_at | timestamptz | When first marked as seen |
| hide_similar | boolean | Auto-close similar content |
| updated_at | timestamptz | Last update timestamp |

### Row Level Security (RLS)

All queries are automatically filtered by `user_id`:
- Users can only access their own data
- Policies enforce authentication
- Data is private by default

## Adding New Features

### Example: Adding Tags

1. **Update Database Schema**:
   ```sql
   ALTER TABLE seen_content ADD COLUMN tags text[];
   ```

2. **Update TypeScript Types** (src/types/index.ts):
   ```typescript
   export interface SeenContent {
     // ... existing fields
     tags?: string[];
   }
   ```

3. **Add UI Component**:
   ```typescript
   // In CurrentPage.tsx or new TagManager.tsx
   const [tags, setTags] = useState<string[]>([]);

   const addTag = async (tag: string) => {
     await supabase
       .from('seen_content')
       .update({ tags: [...tags, tag] })
       .eq('id', contentId);
   };
   ```

4. **Update Database Queries**:
   ```typescript
   const { data } = await supabase
     .from('seen_content')
     .select('*, tags')  // Include tags
     .eq('user_id', userId);
   ```

### Example: Adding Search

1. **Create Search Component** (src/components/Search.tsx):
   ```typescript
   export function Search({ userId }: { userId: string }) {
     const [query, setQuery] = useState('');
     const [results, setResults] = useState<SeenContent[]>([]);

     const handleSearch = async () => {
       const { data } = await supabase
         .from('seen_content')
         .select('*')
         .eq('user_id', userId)
         .or(`title.ilike.%${query}%,url.ilike.%${query}%`);

       setResults(data || []);
     };

     // Render search UI
   }
   ```

2. **Add to Main App**:
   ```typescript
   // In App.tsx
   const [activeTab, setActiveTab] = useState<'current' | 'list' | 'search' | 'settings'>('current');

   // Add search tab button and content
   ```

## Chrome Extension APIs Reference

### Most Commonly Used APIs

1. **chrome.tabs**:
   ```javascript
   // Get current tab
   chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
     const currentTab = tabs[0];
   });

   // Create new tab
   chrome.tabs.create({ url: 'https://example.com' });

   // Close tab
   chrome.tabs.remove(tabId);
   ```

2. **chrome.storage.local**:
   ```javascript
   // Save data
   chrome.storage.local.set({ key: 'value' });

   // Get data
   chrome.storage.local.get(['key'], (result) => {
     console.log(result.key);
   });
   ```

3. **chrome.runtime**:
   ```javascript
   // Send message
   chrome.runtime.sendMessage({ action: 'doSomething' });

   // Listen for messages
   chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
     // Handle message
     sendResponse({ result: 'done' });
     return true; // Required for async responses
   });
   ```

## Testing

### Manual Testing Checklist

- [ ] Authentication works (login/signup)
- [ ] Can mark current page as seen
- [ ] Can mark with "hide similar"
- [ ] Seen list displays correctly
- [ ] Can remove items from seen list
- [ ] Auto-close setting toggles correctly
- [ ] Auto-close works when enabled
- [ ] Data syncs across browser sessions
- [ ] Icons and UI render correctly
- [ ] No console errors

### Testing with Different Scenarios

1. **New User Flow**:
   - Fresh install → Sign up → Mark first page → Check list

2. **Returning User**:
   - Already signed in → Extension should remember session

3. **Multiple Tabs**:
   - Open multiple tabs → Mark some as seen → Test auto-close

4. **Edge Cases**:
   - Very long URLs
   - Special characters in titles
   - Pages without favicons
   - Rapid tab switching

## Common Issues & Solutions

### Issue: Extension not updating after code changes

**Solution**:
1. Run `npm run build`
2. Run `./scripts/build-extension.sh`
3. Go to `chrome://extensions/`
4. Click the refresh icon on SeenIt extension

### Issue: "Cannot read properties of undefined"

**Solution**: Add proper null checks:
```typescript
if (!currentTab || !currentTab.url) return;
```

### Issue: Supabase queries failing

**Solution**:
1. Check `.env` file has correct credentials
2. Verify RLS policies in Supabase dashboard
3. Check network tab in DevTools for error messages

### Issue: Background worker not responding

**Solution**:
1. Check `chrome://extensions/` → SeenIt → "Service Worker" → Inspect
2. View console logs
3. Ensure background.js is copied to dist/

## Performance Optimization Tips

1. **Debounce Searches**: Add delays to search inputs
2. **Limit Query Results**: Use `.limit(50)` on queries
3. **Cache Data**: Store frequently accessed data locally
4. **Lazy Load**: Load seen list only when tab is active
5. **Optimize Images**: Compress extension icons

## Building for Production

1. **Update Version** in `manifest.json`
2. **Run Production Build**:
   ```bash
   npm run build
   ./scripts/build-extension.sh
   ```
3. **Create ZIP**:
   ```bash
   cd dist
   zip -r ../seenit-extension.zip .
   ```
4. **Test Thoroughly** before publishing

## Future Development Ideas

### High Priority
- Content similarity detection using NLP
- Bulk operations (mark multiple as seen)
- Export/import functionality
- Keyboard shortcuts

### Medium Priority
- Statistics dashboard
- Custom categories/tags
- Search and filtering
- Dark mode support

### Low Priority
- Multiple account support
- Browser sync (Firefox, Edge)
- Mobile companion app
- Team sharing features

## Resources

- [Chrome Extension Docs](https://developer.chrome.com/docs/extensions/)
- [Supabase Docs](https://supabase.com/docs)
- [React Docs](https://react.dev)
- [Tailwind CSS](https://tailwindcss.com)

## Getting Help

- Check existing code comments
- Review Chrome extension samples
- Supabase community forum
- Stack Overflow for specific issues
