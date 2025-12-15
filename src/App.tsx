import { useState, useEffect } from 'react';
import { supabase } from './lib/supabase';
import { Auth } from './components/Auth';
import { Header } from './components/Header';
import { CurrentPage } from './components/CurrentPage';
import { SeenList } from './components/SeenList';
import { Settings } from './components/Settings';
import type { User } from './types';

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'current' | 'list' | 'settings'>('current');

  useEffect(() => {
    checkUser();

    const { data: authListener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        (async () => {
          if (session?.user) {
            setUser({
              id: session.user.id,
              email: session.user.email || '',
            });
          } else {
            setUser(null);
          }
        })();
      }
    );

    return () => {
      authListener.subscription.unsubscribe();
    };
  }, []);

  const checkUser = async () => {
    const { data: { session } } = await supabase.auth.getSession();
    if (session?.user) {
      setUser({
        id: session.user.id,
        email: session.user.email || '',
      });
    }
    setLoading(false);
  };

  if (loading) {
    return (
      <div className="w-80 h-96 flex items-center justify-center bg-white">
        <p className="text-gray-600">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return <Auth onAuthSuccess={checkUser} />;
  }

  return (
    <div className="w-96 bg-white">
      <Header userEmail={user.email} onLogout={() => setUser(null)} />

      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab('current')}
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'current'
              ? 'text-blue-600 border-b-2 border-blue-600'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          Current Page
        </button>
        <button
          onClick={() => setActiveTab('list')}
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'list'
              ? 'text-blue-600 border-b-2 border-blue-600'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          Seen List
        </button>
        <button
          onClick={() => setActiveTab('settings')}
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'settings'
              ? 'text-blue-600 border-b-2 border-blue-600'
              : 'text-gray-600 hover:text-gray-800'
          }`}
        >
          Settings
        </button>
      </div>

      <div className="max-h-[500px] overflow-y-auto">
        {activeTab === 'current' && <CurrentPage userId={user.id} />}
        {activeTab === 'list' && <SeenList userId={user.id} />}
        {activeTab === 'settings' && <Settings />}
      </div>
    </div>
  );
}

export default App;
