import { useState, useEffect } from 'react';
import { Trash2, ExternalLink } from 'lucide-react';
import { supabase } from '../lib/supabase';
import type { SeenContent } from '../types';

interface SeenListProps {
  userId: string;
}

export function SeenList({ userId }: SeenListProps) {
  const [seenItems, setSeenItems] = useState<SeenContent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadSeenContent();
  }, [userId]);

  const loadSeenContent = async () => {
    try {
      const { data, error } = await supabase
        .from('seen_content')
        .select('*')
        .eq('user_id', userId)
        .order('seen_at', { ascending: false })
        .limit(50);

      if (!error && data) {
        setSeenItems(data);
      }
    } catch (err) {
      console.error('Error loading seen content:', err);
    } finally {
      setLoading(false);
    }
  };

  const removeItem = async (id: string) => {
    try {
      const { error } = await supabase
        .from('seen_content')
        .delete()
        .eq('id', id);

      if (!error) {
        setSeenItems(seenItems.filter(item => item.id !== id));
      }
    } catch (err) {
      console.error('Error removing item:', err);
    }
  };

  const openUrl = (url: string) => {
    chrome.tabs.create({ url });
  };

  if (loading) {
    return (
      <div className="p-4 text-center text-gray-600">
        Loading seen content...
      </div>
    );
  }

  return (
    <div className="p-4">
      <h2 className="font-semibold text-gray-800 mb-3">
        Recently Seen ({seenItems.length})
      </h2>

      {seenItems.length === 0 ? (
        <div className="text-center text-gray-500 py-8">
          <p className="text-sm">No content marked as seen yet</p>
          <p className="text-xs mt-2">Browse the web and mark pages you've seen!</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {seenItems.map((item) => (
            <div
              key={item.id}
              className="bg-gray-50 rounded-lg p-3 hover:bg-gray-100 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0 mr-2">
                  <div className="flex items-start">
                    {item.favicon && (
                      <img
                        src={item.favicon}
                        alt=""
                        className="w-4 h-4 mr-2 mt-0.5 flex-shrink-0"
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">
                        {item.title}
                      </p>
                      <p className="text-xs text-gray-500 truncate mt-1">
                        {item.url}
                      </p>
                      <p className="text-xs text-gray-400 mt-1">
                        {new Date(item.seen_at).toLocaleDateString()}
                      </p>
                      {item.hide_similar && (
                        <span className="inline-block text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded mt-1">
                          Hide Similar
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => openUrl(item.url)}
                    className="p-1.5 text-blue-600 hover:bg-blue-50 rounded"
                    title="Open URL"
                  >
                    <ExternalLink className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => removeItem(item.id)}
                    className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                    title="Remove"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
