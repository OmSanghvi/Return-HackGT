// Local session: sign-in state lives in the room store, the user is always ME.
import { ME, useRooms } from './data/store';

export function useSession() {
  const signedIn = useRooms((s) => s.signedIn);
  return { loaded: true, signedIn, name: ME.name, firstName: ME.name.split(' ')[0], signOut: useRooms.getState().signOut };
}
