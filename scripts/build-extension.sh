#!/bin/bash

echo "Building SeenIt Chrome Extension..."

npm run build

if [ $? -eq 0 ]; then
    echo "Copying manifest and background script..."
    cp public/manifest.json dist/
    cp public/background.js dist/

    echo ""
    echo "✓ Build completed successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Make sure you have created .env file with Supabase credentials"
    echo "2. Add extension icons (icon16.png, icon48.png, icon128.png) to dist/"
    echo "3. Go to chrome://extensions/"
    echo "4. Enable 'Developer mode'"
    echo "5. Click 'Load unpacked' and select the 'dist' folder"
    echo ""
else
    echo "Build failed!"
    exit 1
fi
