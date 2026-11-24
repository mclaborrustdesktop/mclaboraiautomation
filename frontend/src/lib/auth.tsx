"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken, type AccessMode } from "./api";
import type { Lookups, User } from "./types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  lookups: Lookups | null;
  login: (username: string, password: string) => Promise<void>;
  /** true after signing in with a temporary password set by an administrator */
  mustChangePassword: boolean;
  passwordChanged: () => void;
  logout: () => void;
  hasFeature: (feature: string) => boolean;
  refreshLookups: () => Promise<void>;
  /** null until the server has answered (or if it cannot be reached) */
  accessMode: AccessMode | null;
  /** true on the search-only mirror of the office system: no Add/Edit/Delete for anyone */
  searchOnly: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [lookups, setLookups] = useState<Lookups | null>(null);
  const [loading, setLoading] = useState(true);
  const [mustChangePassword, setMustChange] = useState(false);
  const [accessMode, setAccessMode] = useState<AccessMode | null>(null);
  const [searchOnly, setSearchOnly] = useState(false);

  const refreshLookups = useCallback(async () => {
    try {
      setLookups(await api.lookups());
    } catch {
      /* non-fatal; pages show empty selects */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Ask the server how people get in. If it cannot be reached, mode stays null and the shell says so.
      let mode: AccessMode | null = null;
      try {
        const health = await api.health();
        mode = health.access_mode ?? "login";
        setSearchOnly(health.site_mode === "search-only");
      } catch {
        /* backend not reachable */
      }
      if (cancelled) return;
      setAccessMode(mode);
      // "open" (demo) and "gateway" need no token: the server already knows who is asking.
      if (mode === null || (mode === "login" && !getToken())) {
        setLoading(false);
        return;
      }
      try {
        const me = await api.me();
        if (cancelled) return;
        setUser(me);
        await refreshLookups();
      } catch {
        setToken(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    const onUnauthorized = () => setUser(null);
    window.addEventListener("mclabor:unauthorized", onUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener("mclabor:unauthorized", onUnauthorized);
    };
  }, [refreshLookups]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    setToken(res.access_token);
    setUser(res.user);
    setMustChange(!!res.must_change_password);
    await refreshLookups();
  }, [refreshLookups]);

  const passwordChanged = useCallback(() => setMustChange(false), []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setLookups(null);
    setMustChange(false);
  }, []);

  // On the search-only mirror no one can add, edit or delete (the server refuses it too); the pages hide those controls.
  const hasFeature = useCallback((f: string) => {
    if (!user) return false;
    if ((searchOnly || user.search_only) && f.endsWith(".edit")) return false;
    return user.Profile || user.features.includes(f);
  }, [user, searchOnly]);

  const value = useMemo(() => ({ user, loading, lookups, login, logout, hasFeature, refreshLookups, mustChangePassword, passwordChanged, accessMode, searchOnly: searchOnly || !!user?.search_only }),
    [user, loading, lookups, login, logout, hasFeature, refreshLookups, mustChangePassword, passwordChanged, accessMode, searchOnly]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
