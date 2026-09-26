// Session: mock mode is always ME; real mode is whichever demo account is picked.
import { ME, useRooms } from './data/store';
import { accountLabel, useAccount } from './api/account';
import { REAL_MODE } from './config';

export function useSession() {
  const signedIn = useRooms((s) => s.signedIn);
  const account = useAccount((s) => s.current);
  const name = REAL_MODE ? accountLabel(account) : ME.name;
  return { loaded: true, signedIn, name, firstName: name.split(' ')[0], signOut: useRooms.getState().signOut };
}
