import { Eye, LogOut } from 'lucide-react';
import { supabase } from '../lib/supabase';

interface HeaderProps {
  userEmail?: string;
  onLogout: () => void;
}

export function Header({ userEmail, onLogout }: HeaderProps) {
  const handleLogout = async () => {
    await supabase.auth.signOut();
    onLogout();
  };

  return (
    <div className="bg-blue-600 text-white p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center">
          <Eye className="w-6 h-6 mr-2" />
          <h1 className="text-xl font-bold">SeenIt</h1>
        </div>
        <button
          onClick={handleLogout}
          className="p-2 hover:bg-blue-700 rounded-lg transition-colors"
          title="Sign out"
        >
          <LogOut className="w-5 h-5" />
        </button>
      </div>
      {userEmail && (
        <p className="text-sm text-blue-100 mt-1">{userEmail}</p>
      )}
    </div>
  );
}
