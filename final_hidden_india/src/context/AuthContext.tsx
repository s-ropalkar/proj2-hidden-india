/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import * as api from '../api';
import type { AuthUser } from '../api';
import type { ScreenId } from '../types';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<ScreenId>;
  register: (name: string, email: string, password: string) => Promise<ScreenId>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  setUserLocal: (user: AuthUser) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    if (!api.isLoggedIn()) {
      setUser(null);
      return;
    }
    try {
      const me = await api.getMe();
      setUser(me);
    } catch {
      api.logout();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refreshUser().finally(() => setLoading(false));
  }, [refreshUser]);

  const login = async (email: string, password: string): Promise<ScreenId> => {
    const { user: u } = await api.login(email, password);
    setUser(u);
    return api.homeScreenForUser(u) as ScreenId;
  };

  const register = async (name: string, email: string, password: string): Promise<ScreenId> => {
    const { user: u } = await api.register(name, email, password);
    setUser(u);
    return 'artistic-echoes';
  };

  const logout = () => {
    api.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        register,
        logout,
        refreshUser,
        setUserLocal: setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
