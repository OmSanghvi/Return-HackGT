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

/** Human label for an account id: "Account 1 (demo-alice)", never a hard-coded name. */
export function accountLabel(id: string): string {
  const index = DEMO_ACCOUNTS.indexOf(id);
  return index >= 0 ? `Account ${index + 1}` : id;
}
