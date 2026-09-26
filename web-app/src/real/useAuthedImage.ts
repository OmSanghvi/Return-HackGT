// Every image route (upload source, selection mask preview, asset preview)
// requires the X-SketchScape-Dev-User header, so a plain `<img src>` can't
// load it directly. This fetches it with the header and hands back a blob
// object URL, re-fetching whenever the path or the chosen account changes,
// and revoking the previous URL so blobs don't leak across switches.
import { useEffect, useState } from 'react';
import { fetchImageObjectUrl } from '../api/client';
import { useAccount } from '../api/account';

export function useAuthedImage(path: string | null | undefined): { url: string | null; error: boolean } {
  const account = useAccount((s) => s.current);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!path) {
      setUrl(null);
      setError(false);
      return;
    }
    let objectUrl: string | null = null;
    let cancelled = false;
    setError(false);
    fetchImageObjectUrl(path)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // account is in the deps so switching accounts re-fetches under the new identity.
  }, [path, account]);

  return { url, error };
}
