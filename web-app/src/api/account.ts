// The account picker's state: which of the two hardcoded SKETCHSCAPE_DEMO_USERS
// accounts is "me" right now. Persisted so a reload keeps the choice, exactly
// like the mock-mode session it stands in for (web-app-foundation skill).
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEMO_ACCOUNTS } from '../config';

interface AccountState {
  current: string;
  setAccount: (id: string) => void;
}

export const useAccount = create<AccountState>()(
  persist(
    (set) => ({
      current: DEMO_ACCOUNTS[0] ?? 'demo-alice',
      setAccount: (id: string) => set({ current: id }),
    }),
    { name: 'sketchscape-real-account' },
  ),
);

/** Human name for an account id: "demo-alice" -> "Alice". Unknown/empty ids read as "Someone". */
export function accountLabel(id: string): string {
  const name = id.replace(/^demo-/, '').replace(/[-_]+/g, ' ').trim();
  return name ? name.replace(/\b\w/g, (c) => c.toUpperCase()) : 'Someone';
}
