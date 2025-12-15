import { useState, useEffect } from 'react';
import { Check, X, ExternalLink } from 'lucide-react';
import { supabase } from '../lib/supabase';
import type { TabInfo, SeenContent } from '../types';

interface CurrentPageProps {
  userId: string;
}

export function CurrentPage({ userId }: CurrentPageProps) {
  const [currentTab, setCurrentTab] = useState<TabInfo | null>(null);
  const [isSeen, setIsSeen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [seenContent, setSeenContent] = useState<SeenContent | null>(null);

  useEffect(() => {
    loadCurrentTab();
  }, []);

  const loadCurrentTab = async () => {
    try {
      chrome.runtime.sendMessage({ action: 'getCurrentTab' }, async (response) => {
        if (response && response.url) {
          setCurrentTab(response);
          await checkIfSeen(response.url);
        }
        setLoading(false);
      });
    } catch (err) {
      console.error('Error loading tab:', err);
      setLoading(false);
    }
  };

  const checkIfSeen = async (url: string) => {
    try {
      const { data } = await supabase
        .from('seen_content')
        .select('*')
        .eq('user_id', userId)
        .eq('url', url)
        .maybeSingle();

      if (data) {
        setIsSeen(true);
        setSeenContent(data);
      }
    } catch (err) {
      console.error('Error checking if seen:', err);
    }
  };

  const markAsSeen = async (hideSimilar: boolean = false) => {
    if (!currentTab) return;

    try {
      const { error } = await supabase
        .from('seen_content')
        .insert({
          user_id: userId,
          url: currentTab.url,
          title: currentTab.title,
          favicon: currentTab.favicon,
          hide_similar: hideSimilar,
        });

      if (!error) {
        setIsSeen(true);
        await checkIfSeen(currentTab.url);
      }
    } catch (err) {
      console.error('Error marking as seen:', err);
    }
  };

  const removeFromSeen = async () => {
    if (!currentTab) return;

    try {
      const { error } = await supabase
        .from('seen_content')
        .delete()
        .eq('user_id', userId)
        .eq('url', currentTab.url);

      if (!error) {
        setIsSeen(false);
        setSeenContent(null);
      }
    } catch (err) {
      console.error('Error removing from seen:', err);
    }
  };

  if (loading) {
    return (
      <div className="p-4 text-center text-gray-600">
        Loading current page...
      </div>
    );
  }

  if (!currentTab) {
    return (
      <div className="p-4 text-center text-gray-600">
        No active tab found
      </div>
    );
  }

  return (
    <div className="p-4 border-b border-gray-200">
      <h2 className="font-semibold text-gray-800 mb-3">Current Page</h2>

      <div className="bg-gray-50 rounded-lg p-3 mb-3">
        <div className="flex items-start">
          {currentTab.favicon && (
            <img
              src={currentTab.favicon}
              alt=""
              className="w-4 h-4 mr-2 mt-1 flex-shrink-0"
            />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-800 truncate">
              {currentTab.title}
            </p>
            <p className="text-xs text-gray-500 truncate mt-1">
              {currentTab.url}
            </p>
          </div>
        </div>
      </div>

      {isSeen ? (
        <div className="space-y-2">
          <div className="flex items-center text-green-600 bg-green-50 p-3 rounded-lg">
            <Check className="w-5 h-5 mr-2 flex-shrink-0" />
            <span className="text-sm font-medium">
              You've seen this page before
            </span>
          </div>
          {seenContent && seenContent.seen_at && (
            <p className="text-xs text-gray-500 text-center">
              First seen: {new Date(seenContent.seen_at).toLocaleDateString()}
            </p>
          )}
          <button
            onClick={removeFromSeen}
            className="w-full bg-gray-100 text-gray-700 py-2 px-4 rounded-lg hover:bg-gray-200 transition-colors text-sm"
          >
            Remove from seen
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center text-blue-600 bg-blue-50 p-3 rounded-lg">
            <ExternalLink className="w-5 h-5 mr-2 flex-shrink-0" />
            <span className="text-sm font-medium">
              This is a new page
            </span>
          </div>
          <button
            onClick={() => markAsSeen(false)}
            className="w-full bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 transition-colors text-sm"
          >
            Mark as Seen
          </button>
          <button
            onClick={() => markAsSeen(true)}
            className="w-full bg-orange-600 text-white py-2 px-4 rounded-lg hover:bg-orange-700 transition-colors text-sm"
          >
            Mark as Seen & Hide Similar
          </button>
        </div>
      )}
    </div>
  );
}
