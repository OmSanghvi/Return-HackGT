using System;
using System.Collections.Generic;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>
    /// The headset frontend. A dusk sky with the worlds you're already in and ready to enter as portals on a ring;
    /// an account picker before you're signed in; a wrist menu; and a fade into the room's world. Rig-agnostic: give it a head
    /// (and optionally a left hand) transform. Inviting, uploading photos and creating rooms happen on the web, not here.
    /// </summary>
    public class HubController : MonoBehaviour
    {
        public const float RingRadius = ReturnSpatial.PortalRingRadius;

        public IRoomStore store;
        public Transform head, leftHand;
        public IWorldLoader loader;
        public float fadeSeconds = 1.1f;

        public WorldSession Session { get; private set; }
        public SpatialPanel Work { get; private set; }
        public IReadOnlyList<PortalCard> Cards => _cards;
        public bool RingVisible => _ring != null && _ring.gameObject.activeSelf;
        public bool WorkVisible => Work != null && Work.gameObject.activeSelf;

        /// <summary>Fired once the account picker signs someone in, with their display name.</summary>
        public event Action<string> SignedIn;
        /// <summary>Fired after the ring is (re)built, portals in ring order. For later work: greeting animation, audio, haptics.</summary>
        public event Action<IReadOnlyList<RoomPortal>> PortalsLaidOut;
        /// <summary>Fired right before a world is entered. For later work: step-through transitions, audio.</summary>
        public event Action<Room, RoomPortal> EnteringRoom;

        static HubController _active;
        Transform _hubRoot, _ring, _persistent;
        readonly List<PortalCard> _cards = new List<PortalCard>();
        float _yaw; string _ringIds = "";

        public void Bootstrap()
        {
            if (head == null && Camera.main != null) head = Camera.main.transform;
            _yaw = head != null ? head.eulerAngles.y : 0f;

            _hubRoot = new GameObject("ReturnHub").transform; _hubRoot.SetParent(transform, false);
            _persistent = new GameObject("ReturnPersistent").transform; _persistent.SetParent(transform, false);
            _ring = new GameObject("Ring").transform; _ring.SetParent(_hubRoot, false);

            _active = this;
            ThemeManager.SetForced(ReturnTheme.Dusk);
            var env = HubEnvironment.Build(_hubRoot, head, SceneKey.Hub, true, 150f, true); // extras: water floor, fireflies, motes, lanterns, ambience
            env.transform.rotation = Quaternion.Euler(0, _yaw, 0);

            var camGo = head != null ? (head.GetComponent<Camera>() != null ? head : head.GetComponentInChildren<Camera>()?.transform ?? head) : null;
            var fade = camGo != null ? ScreenFade.Attach(camGo) : ScreenFade.Attach(new GameObject("NoHead").transform);
            Session = new WorldSession(loader ?? new StubWorldLoader(), fade, head, HubVisible, new PortalTransition(head)) { fadeSeconds = fadeSeconds };

            Work = SpatialPanel.Create("WorkPanel", 900, 520, _hubRoot);
            Work.gameObject.SetActive(false);
            var cam = camGo != null ? camGo.GetComponent<Camera>() : null;
            if (cam != null) Work.SetEventCamera(cam);

            BuildHandMenu(cam);
            store.Changed += OnStore;
            RebuildRing();
            if (store.SignedIn) ShowRing(); else ShowPicker();
            HubIntro.Attach(this, store, head, _hubRoot);
        }

        void OnDestroy()
        {
            if (store != null) store.Changed -= OnStore;
            if (_active == this) { _active = null; ThemeManager.SetForced(null); } // a newer hub owns the theme now
        }

        // ---- account picker ---------------------------------------------------------------
        public void ShowPicker()
        {
            _ring.gameObject.SetActive(false);
            Work.gameObject.SetActive(true);
            PlaceWork();
            BuildPicker();
        }

        void BuildPicker()
        {
            foreach (Transform t in Work.rect) Destroy(t.gameObject);
            var col = UI.V(Work.rect, "Picker", 26, new RectOffset(56, 56, 48, 48), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 40); UI.Border(col, ColorRole.GlassEdge, 40, 2);
            UI.Text(col, "Who's " + UI.Em("here") + "?", TextStyle.Title, ColorRole.OnGlass, TextAlignmentOptions.Center);
            var row = UI.H(col, "Accounts", 28, null, TextAnchor.MiddleCenter); UI.Size(row, -1, 220);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;
            foreach (var acct in RoomLogic.Accounts)
            {
                var card = UI.V(row, "Account:" + acct.id, 14, UI.Pad(24), TextAnchor.MiddleCenter); UI.Size(card, 210, 220);
                UI.Bg(card, ColorRole.GlassStrong, 28); UI.Border(card, ColorRole.GlassEdge, 28, 2);
                Avatars.Create(card, acct.name, 84, false, true);
                UI.Text(card, acct.name.Split(' ')[0], TextStyle.Title, ColorRole.OnGlass, TextAlignmentOptions.Center);
                var hit = UI.Img(card, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false;
                UI.Stretch(hit.rectTransform); UI.Overlay(hit.rectTransform);
                var id = acct.id; var name = acct.name;
                var p = card.gameObject.AddComponent<Pressable>(); p.onClick = () => Pick(id, name); p.hoverScale = 1.03f;
            }
        }

        void Pick(string accountId, string displayName)
        {
            store.SignIn(accountId);
            SignedIn?.Invoke(displayName);
            RebuildRing();
            ShowRing();
        }

        // ---- ring / work panel visibility -------------------------------------------------
        public void ShowRing()
        {
            if (Work != null) Work.gameObject.SetActive(false);
            _ring.gameObject.SetActive(store.SignedIn);
            LayoutRing();
        }

        void PlaceWork() { if (head != null) Work.PlaceInFront(head, 1.6f, -0.05f); }

        /// <summary>Face the ring (and the work panel) the way the viewer is looking now.</summary>
        public void Recenter()
        {
            if (head == null) return;
            _yaw = head.eulerAngles.y; LayoutRing(); if (WorkVisible) PlaceWork();
        }

        // ---- ring ------------------------------------------------------------------------
        List<Room> RingRooms() => RoomLogic.ReadyRoomsFor(store.Rooms, store.CurrentAccountId);

        void OnStore()
        {
            if (Session != null && Session.State == SessionState.InWorld) return;
            if (!store.SignedIn) { if (RingVisible) ShowPicker(); return; }
            var ids = string.Join(",", RingRooms().Select(r => r.id));
            if (ids != _ringIds) RebuildRing(); else foreach (var c in _cards) c.Refresh(store);
        }

        void RebuildRing()
        {
            foreach (var c in _cards) if (c != null) Destroy(c.gameObject);
            _cards.Clear();
            var rooms = RingRooms(); _ringIds = string.Join(",", rooms.Select(r => r.id));
            foreach (var r in rooms) _cards.Add(PortalCard.Create(_ring, r, store, EnterRoom));
            LayoutRing();
            PortalsLaidOut?.Invoke(_cards.Where(c => c != null).Select(c => c.portal).ToList());
        }

        void LayoutRing()
        {
            int n = _cards.Count;
            float span = Mathf.Min(150f, 38f * (n - 1));
            for (int i = 0; i < n; i++)
            {
                float t = n == 1 ? 0.5f : i / (float)(n - 1);
                float a = Mathf.Lerp(-span / 2f, span / 2f, t);
                var dir = Quaternion.Euler(0, _yaw + a, 0) * Vector3.forward;
                var tr = _cards[i] != null ? _cards[i].transform : null;
                if (tr == null) continue;
                tr.position = new Vector3(0, 0, 0) + dir * RingRadius; tr.rotation = Quaternion.LookRotation(dir);
            }
        }

        // ---- worlds ----------------------------------------------------------------------
        /// <summary>The one way in: fires EnteringRoom, then loads the world if it's ready.</summary>
        public void EnterRoom(Room room, RoomPortal portal)
        {
            EnteringRoom?.Invoke(room, portal);
            Enter(room, portal);
        }

        void Enter(Room room, RoomPortal portal) { if (Session.State == SessionState.Hub && room.phase == Phase.Ready) LogFaults(Session.EnterAsync(room, portal)); }
        public void ExitWorld() { LogFaults(Session.ExitAsync()); }

        /// <summary>Fire-and-forget, but a fault still reaches the log (logcat on Quest) instead of vanishing with the task.</summary>
        static void LogFaults(System.Threading.Tasks.Task t) =>
            t.ContinueWith(x => Debug.LogException(x.Exception), System.Threading.Tasks.TaskContinuationOptions.OnlyOnFaulted);

        void HubVisible(bool visible)
        {
            _hubRoot.gameObject.SetActive(visible);
            ThemeManager.SetForced(visible ? ReturnTheme.Dusk : (ReturnTheme?)null);
            if (visible) Recenter();
        }

        // ---- wrist menu --------------------------------------------------------------------
        void BuildHandMenu(Camera cam)
        {
            var p = SpatialPanel.Create("HandMenu", 420, 110, _persistent);
            if (cam != null) p.SetEventCamera(cam);
            var m = HandMenu.Create(p.rect, new[]
            {
                new HandMenu.Item("home", "Hub", () => { if (Session.State == SessionState.InWorld) ExitWorld(); else if (store.SignedIn) ShowRing(); else ShowPicker(); }),
                new HandMenu.Item("pinch", "Recenter", Recenter),
            });
            UI.Anchor(m, new Vector2(0.5f, 0.5f), Vector2.zero);
            if (leftHand != null)
            {
                p.transform.SetParent(leftHand, false);
                p.transform.localPosition = new Vector3(0, 0.11f, 0.02f); p.transform.localRotation = Quaternion.Euler(-70, 0, 0); p.transform.localScale = Vector3.one * 0.0006f;
            }
            else
            {
                var lf = p.gameObject.AddComponent<LazyFollow>(); lf.head = head; p.transform.localScale = Vector3.one * 0.001f;
                if (head != null) p.PlaceInFront(head, 0.7f, -0.42f);
            }
        }
    }
}
