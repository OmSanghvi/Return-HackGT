// SketchScape SharedRoomSession — the shared layer's data for one headset (WEB_TO_QUEST_PIPELINE.md 1b, 4, 5).
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// Holds the current account (PlayerPrefs, default from the room spec), reads
// GET {api_base}/v1/rooms/{project_id}/shared as that account (X-SketchScape-Dev-User),
// falls back to the baked snapshot (Resources/SharedSnapshots/<project_id>) when the API
// is unreachable, and opens letters (POST /v1/rooms/{p}/letters/{id}/open, then re-reads).
// Public API (also for Unity_RunCommand tests): SwitchTo(accountId), Refresh(), OpenLetter(letterId).
// No Editor APIs; nothing runs per frame.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace SketchScape
{
    [DisallowMultipleComponent]
    public class SharedRoomSession : MonoBehaviour
    {
        public const string AccountHeader = "X-SketchScape-Dev-User";

        [Tooltip("The room spec's shared block (set by RoomKit).")]
        public SharedRoomConfig config = new SharedRoomConfig();
        [Tooltip("Seconds before one API request gives up.")]
        public int timeoutSeconds = 8;
        [Tooltip("Extra attempts after a failed request (network errors and 5xx only).")]
        public int retries = 2;
        public bool fetchOnStart = true;

        public string CurrentAccount { get; private set; }
        public SharedView View { get; private set; }
        /// <summary>"live", "snapshot" or "none".</summary>
        public string Source { get; private set; }
        public string LastError { get; private set; }
        public bool Busy { get { return _requests > 0; } }
        /// <summary>Last letter action, for tests and the switcher's status plate.</summary>
        public string LastLetterEvent { get; private set; }

        public event Action<SharedView> ViewChanged;
        public event Action<string> AccountChanged;
        /// <summary>A letter the viewer may read was opened (fires after the re-read view is applied).</summary>
        public event Action<string> LetterOpened;
        /// <summary>(letter_id, reason): the viewer may not open it, or opening failed.</summary>
        public event Action<string, string> LetterRefused;
        public event Action StatusChanged;

        SharedSnapshot _snapshot;
        bool _snapshotTried;
        int _requests;
        int _fetchSerial;
        string _pendingOpened;
        readonly Dictionary<string, SharedView> _liveViews = new Dictionary<string, SharedView>();
        readonly Dictionary<string, Texture2D> _textures = new Dictionary<string, Texture2D>();

        string PrefKey { get { return "SketchScape.SharedRoom." + config.project_id + ".account"; } }
        public bool Enabled { get { return config != null && config.enabled && !string.IsNullOrEmpty(config.project_id); } }

        void Awake()
        {
            if (config == null) config = new SharedRoomConfig();
            if (config.accounts == null) config.accounts = new string[0];
            if (config.labels == null) config.labels = new string[0];
            Source = "none";
            LastError = "";
            LastLetterEvent = "";
            CurrentAccount = LoadAccount();
        }

        void Start()
        {
            if (!Enabled) return;
            ApplyCachedOrSnapshot(CurrentAccount);
            if (fetchOnStart) Refresh();
        }

        void OnDestroy()
        {
            foreach (var t in _textures.Values) if (t != null) Destroy(t);
            _textures.Clear();
        }

        // ------------------------------------------------------------------
        // Public API
        // ------------------------------------------------------------------

        /// <summary>Switch the viewing account (persisted). Shows the cached/snapshot view at once, then re-reads live.</summary>
        public void SwitchTo(string accountId)
        {
            if (!Enabled) return;
            if (string.IsNullOrEmpty(accountId) || Array.IndexOf(config.accounts, accountId) < 0)
            {
                LastError = "unknown account '" + accountId + "'";
                RaiseStatus();
                return;
            }
            bool changed = accountId != CurrentAccount;
            CurrentAccount = accountId;
            try { PlayerPrefs.SetString(PrefKey, accountId); PlayerPrefs.Save(); } catch (Exception) { }
            if (changed && AccountChanged != null) AccountChanged(accountId);
            ApplyCachedOrSnapshot(accountId);
            Refresh();
        }

        /// <summary>Re-read the view for the current account.</summary>
        public void Refresh()
        {
            if (!Enabled || !isActiveAndEnabled) return;
            StartCoroutine(FetchView(CurrentAccount));
        }

        /// <summary>
        /// Open a letter as the current account. A sealed letter opens only for a recipient
        /// (can_open); a letter the viewer can already read just shows its page. Returns false
        /// when refused at once (LetterRefused says why).
        /// </summary>
        public bool OpenLetter(string letterId)
        {
            if (!Enabled) return false;
            var letter = View != null ? View.FindLetter(letterId) : null;
            if (letter == null) { Refuse(letterId, "no such letter"); return false; }
            if (letter.opened && letter.HasPage)
            {
                LastLetterEvent = "shown " + letterId;
                if (LetterOpened != null) LetterOpened(letterId);
                RaiseStatus();
                return true;
            }
            if (!letter.can_open)
            {
                Refuse(letterId, "sealed: only " + RecipientLabels(letter) + " can open it");
                return false;
            }
            if (!isActiveAndEnabled) return false;
            StartCoroutine(OpenRoutine(letterId, CurrentAccount));
            return true;
        }

        /// <summary>RoomKit's Editor bake: show a view (from the snapshot) without events or requests.</summary>
        public void UsePreview(SharedView view)
        {
            if (view == null) return;
            view.Normalize();
            View = view;
            Source = "snapshot";
        }

        public string LabelFor(string account)
        {
            if (View != null)
            {
                var a = View.FindAccount(account);
                if (a != null && !string.IsNullOrEmpty(a.label)) return a.label;
            }
            int i = Array.IndexOf(config.accounts, account);
            if (i >= 0 && i < config.labels.Length && !string.IsNullOrEmpty(config.labels[i])) return config.labels[i];
            return string.IsNullOrEmpty(account) ? "someone" : account;
        }

        public string DisplayNameFor(string account)
        {
            var a = View != null ? View.FindAccount(account) : null;
            return a != null && !string.IsNullOrEmpty(a.display_name) ? a.display_name : "";
        }

        public Color ColorFor(string account)
        {
            int i = Array.IndexOf(config.accounts, account);
            var fallback = i == 1 ? SharedPalette.Account2 : (i == 0 ? SharedPalette.Account1 : new Color(0.6f, 0.6f, 0.62f));
            var a = View != null ? View.FindAccount(account) : null;
            return a != null ? SharedPalette.Parse(a.color, fallback) : fallback;
        }

        public string RecipientLabels(SharedLetter letter)
        {
            if (letter == null || letter.recipients == null || letter.recipients.Length == 0) return "its recipient";
            var sb = new StringBuilder();
            for (int i = 0; i < letter.recipients.Length; i++)
            {
                if (i > 0) sb.Append(i == letter.recipients.Length - 1 ? " and " : ", ");
                sb.Append(LabelFor(letter.recipients[i]));
            }
            return sb.ToString();
        }

        /// <summary>Absolute URL for an API path ("/v1/..."); absolute URLs pass through.</summary>
        public string Api(string path)
        {
            if (string.IsNullOrEmpty(path)) return "";
            if (path.StartsWith("http://") || path.StartsWith("https://")) return path;
            string b = (config.api_base ?? "").TrimEnd('/');
            return b + (path.StartsWith("/") ? path : "/" + path);
        }

        /// <summary>The page texture of a letter the viewer may read: downloaded with the account header, else the snapshot's PNG.</summary>
        public void FetchLetterTexture(SharedLetter letter, Action<Texture2D> done)
        {
            if (letter == null || done == null) return;
            string key = CurrentAccount + "|" + letter.letter_id;
            Texture2D cached;
            if (_textures.TryGetValue(key, out cached) && cached != null) { done(cached); return; }
            if (string.IsNullOrEmpty(letter.texture_url) || !isActiveAndEnabled) { done(SnapshotTexture(letter.letter_id)); return; }
            StartCoroutine(TextureRoutine(letter, key, CurrentAccount, done));
        }

        public string Describe()
        {
            var v = View;
            return "account=" + CurrentAccount + " source=" + Source + " busy=" + Busy +
                   " notes=" + (v != null ? v.notes.Length : 0) + " letters=" + (v != null ? v.letters.Length : 0) +
                   " objects=" + (v != null ? v.objects.Length : 0) +
                   (string.IsNullOrEmpty(LastError) ? "" : " error=" + LastError) +
                   (string.IsNullOrEmpty(LastLetterEvent) ? "" : " letter=" + LastLetterEvent);
        }

        // ------------------------------------------------------------------
        // Internals
        // ------------------------------------------------------------------

        string LoadAccount()
        {
            string fallback = !string.IsNullOrEmpty(config.default_account) ? config.default_account
                : (config.accounts.Length > 0 ? config.accounts[0] : "");
            string saved = "";
            try { saved = PlayerPrefs.GetString(PrefKey, ""); } catch (Exception) { }
            return !string.IsNullOrEmpty(saved) && Array.IndexOf(config.accounts, saved) >= 0 ? saved : fallback;
        }

        void ApplyCachedOrSnapshot(string account)
        {
            SharedView v;
            if (_liveViews.TryGetValue(account, out v)) { Apply(v, "live"); return; }
            v = SnapshotView(account);
            if (v != null) Apply(v, "snapshot");
        }

        public SharedView SnapshotView(string account)
        {
            if (!_snapshotTried)
            {
                _snapshotTried = true;
                try
                {
                    var asset = string.IsNullOrEmpty(config.snapshot_resource) ? null : Resources.Load<TextAsset>(config.snapshot_resource);
                    if (asset != null) _snapshot = JsonUtility.FromJson<SharedSnapshot>(asset.text);
                }
                catch (Exception e) { LastError = "snapshot unreadable: " + e.Message; }
            }
            var view = _snapshot != null ? _snapshot.ViewFor(account) : null;
            if (view != null) view.Normalize();
            return view;
        }

        Texture2D SnapshotTexture(string letterId)
        {
            if (string.IsNullOrEmpty(config.snapshot_resource) || string.IsNullOrEmpty(letterId)) return null;
            return Resources.Load<Texture2D>(config.snapshot_resource + "/" + letterId);
        }

        void Apply(SharedView view, string source)
        {
            if (view == null) return;
            View = view;
            Source = source;
            if (ViewChanged != null) ViewChanged(view);
            if (_pendingOpened != null && source == "live")
            {
                string id = _pendingOpened;
                _pendingOpened = null;
                var letter = view.FindLetter(id);
                if (letter != null && letter.HasPage)
                {
                    LastLetterEvent = "opened " + id;
                    if (LetterOpened != null) LetterOpened(id);
                }
                else Refuse(id, "opened, but the page is not readable yet");
            }
            RaiseStatus();
        }

        void Refuse(string letterId, string reason)
        {
            LastLetterEvent = "refused " + letterId + ": " + reason;
            if (LetterRefused != null) LetterRefused(letterId, reason);
            RaiseStatus();
        }

        void RaiseStatus()
        {
            if (StatusChanged != null) StatusChanged();
        }

        static bool Retryable(UnityWebRequest req)
        {
            long code = req.responseCode;
            return code == 0 || code >= 500 || code == 408 || code == 429;
        }

        static string ErrorOf(UnityWebRequest req)
        {
            return (req.responseCode > 0 ? "HTTP " + req.responseCode + " " : "") + (req.error ?? "request failed");
        }

        IEnumerator FetchView(string account)
        {
            int serial = ++_fetchSerial;
            _requests++;
            RaiseStatus();
            string url = Api("/v1/rooms/" + config.project_id + "/shared");
            string text = null, err = null;
            for (int attempt = 0; attempt <= retries; attempt++)
            {
                using (var req = UnityWebRequest.Get(url))
                {
                    req.SetRequestHeader(AccountHeader, account);
                    req.timeout = Mathf.Max(1, timeoutSeconds);
                    yield return req.SendWebRequest();
                    if (req.result == UnityWebRequest.Result.Success) { text = req.downloadHandler.text; break; }
                    err = ErrorOf(req);
                    if (!Retryable(req)) break;
                }
                if (attempt < retries) yield return new WaitForSecondsRealtime(0.75f * (attempt + 1));
            }
            _requests--;

            SharedView view = null;
            if (text != null)
            {
                try { view = JsonUtility.FromJson<SharedView>(text); }
                catch (Exception e) { err = "unreadable view: " + e.Message; }
                if (view != null) view.Normalize();
            }
            if (view != null)
            {
                _liveViews[account] = view;
                LastError = "";
            }
            else LastError = err ?? "no view";

            // A newer request or an account switch supersedes this one.
            if (serial != _fetchSerial || account != CurrentAccount) { RaiseStatus(); yield break; }
            if (view != null) Apply(view, "live");
            else
            {
                if (View == null || Source != "live" || View.viewer != account) ApplyCachedOrSnapshot(account);
                if (_pendingOpened != null) { string id = _pendingOpened; _pendingOpened = null; Refuse(id, "opened, but the room could not re-read it: " + LastError); }
                RaiseStatus();
            }
        }

        IEnumerator OpenRoutine(string letterId, string account)
        {
            _requests++;
            LastLetterEvent = "opening " + letterId;
            RaiseStatus();
            string url = Api("/v1/rooms/" + config.project_id + "/letters/" + letterId + "/open");
            bool ok = false;
            string err = null;
            for (int attempt = 0; attempt <= retries; attempt++)
            {
                using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
                {
                    req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes("{}"));
                    req.uploadHandler.contentType = "application/json";
                    req.downloadHandler = new DownloadHandlerBuffer();
                    req.SetRequestHeader("Content-Type", "application/json");
                    req.SetRequestHeader(AccountHeader, account);
                    req.timeout = Mathf.Max(1, timeoutSeconds);
                    yield return req.SendWebRequest();
                    if (req.result == UnityWebRequest.Result.Success) { ok = true; break; }
                    err = ErrorOf(req);
                    if (!Retryable(req)) break;
                }
                if (attempt < retries) yield return new WaitForSecondsRealtime(0.75f * (attempt + 1));
            }
            _requests--;
            if (!ok)
            {
                Refuse(letterId, "could not open (" + err + ")");
                yield break;
            }
            if (account != CurrentAccount) { RaiseStatus(); yield break; }
            _pendingOpened = letterId;
            yield return FetchView(account);
        }

        IEnumerator TextureRoutine(SharedLetter letter, string key, string account, Action<Texture2D> done)
        {
            _requests++;
            Texture2D tex = null;
            for (int attempt = 0; attempt <= retries && tex == null; attempt++)
            {
                using (var req = UnityWebRequestTexture.GetTexture(Api(letter.texture_url), false))
                {
                    req.SetRequestHeader(AccountHeader, account);
                    req.timeout = Mathf.Max(2, timeoutSeconds * 2);
                    yield return req.SendWebRequest();
                    if (req.result == UnityWebRequest.Result.Success) tex = DownloadHandlerTexture.GetContent(req);
                    else if (!Retryable(req)) break;
                }
                if (tex == null && attempt < retries) yield return new WaitForSecondsRealtime(0.75f * (attempt + 1));
            }
            _requests--;
            if (tex != null)
            {
                tex.name = "Letter " + letter.letter_id;
                tex.wrapMode = TextureWrapMode.Clamp;
                Texture2D old;
                if (_textures.TryGetValue(key, out old) && old != null && old != tex) Destroy(old);
                _textures[key] = tex;
            }
            else tex = SnapshotTexture(letter.letter_id);
            RaiseStatus();
            done(tex);
        }
    }
}
