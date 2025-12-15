import { useState, useEffect } from 'react';
import { Settings as SettingsIcon } from 'lucide-react';

export function Settings() {
  const [autoClose, setAutoClose] = useState(false);

  useEffect(() => {
    chrome.storage.local.get(['autoClose'], (result) => {
      setAutoClose(result.autoClose || false);
    });
  }, []);

  const handleAutoCloseChange = (checked: boolean) => {
    setAutoClose(checked);
    chrome.storage.local.set({ autoClose: checked });
  };

  return (
    <div className="p-4 border-t border-gray-200">
      <div className="flex items-center mb-3">
        <SettingsIcon className="w-5 h-5 mr-2 text-gray-700" />
        <h2 className="font-semibold text-gray-800">Settings</h2>
      </div>

      <div className="space-y-3">
        <label className="flex items-center justify-between cursor-pointer">
          <div>
            <p className="text-sm font-medium text-gray-700">Auto-close seen pages</p>
            <p className="text-xs text-gray-500">Automatically close tabs marked as "Hide Similar"</p>
          </div>
          <div className="relative">
            <input
              type="checkbox"
              checked={autoClose}
              onChange={(e) => handleAutoCloseChange(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
          </div>
        </label>
      </div>

      <div className="mt-4 pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-500">
          SeenIt helps you track content you've already seen. Configure your Supabase credentials to sync across devices.
        </p>
      </div>
    </div>
  );
}
