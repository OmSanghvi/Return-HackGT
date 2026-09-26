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
    /// The headset frontend. A dusk sky with your rooms as portals on a ring; glass panels for sign-in, creating a room and adding photos;
    /// a wrist menu; and a fade into the room's world. Rig-agnostic: give it a head (and optionally a left hand) transform.
    /// </summary>
    public class HubController : MonoBehaviour
    {
        public const float RingRadius = ReturnSpatial.PortalRingRadius;

        public IRoomStore store;
        public Transform head, leftHand;
        public IWorldLoader loader;
        public float fadeSeconds = 1.1f;

        public WorldSession Session { get; private set; }
        public ScreenRouter Router { get; private set; }
        public SpatialPanel Work { get; private set; }
        public IReadOnlyList<PortalCard> Cards => _cards;
        public bool RingVisible => _ring != null && _ring.gameObject.activeSelf;
        public bool WorkVisible => Work != null && Work.gameObject.activeSelf;

        static HubController _active;
        Transform _hubRoot, _ring, _persistent;
        readonly List<PortalCard> _cards = new List<PortalCard>();
        float _yaw; string _ringIds = "";
        bool _immediate;

        public void Bootstrap()
        {
            _immediate = !Application.isPlaying;
            if (head == null && Camera.main != null) head = Camera.main.transform;
            _yaw = head != null ? head.eulerAngles.y : 0f;

            _hubRoot = new GameObject("ReturnHub").transform; _hubRoot.SetParent(transform, false);
            _persistent = new GameObject("ReturnPersistent").transform; _persistent.SetParent(transform, false);
            _ring = new GameObject("Ring").transform; _ring.SetParent(_hubRoot, false);

            _active = this;
            ThemeManager.SetForced(ReturnTheme.Dusk);
            var env = HubEnvironment.Build(_hubRoot, head, SceneKey.Hub, true, 150f);
            env.transform.rotation = Quaternion.Euler(0, _yaw, 0);

            var camGo = head != null ? (head.GetComponent<Camera>() != null ? head : head.GetComponentInChildren<Camera>()?.transform ?? head) : null;
            var fade = camGo != null ? ScreenFade.Attach(camGo) : ScreenFade.Attach(new GameObject("NoHead").transform);
            Session = new WorldSession(loader ?? new StubWorldLoader(), fade, head, HubVisible) { fadeSeconds = fadeSeconds };

            Work = SpatialPanel.Create("WorkPanel", 1360, 860, _hubRoot);
            Work.gameObject.SetActive(false);
            var cam = camGo != null ? camGo.GetComponent<Camera>() : null;
            if (cam != null) Work.SetEventCamera(cam);
            var ctx = new AppContext { store = store, backdrop = new NullBackdrop(), panel = Work.rect, enterWorld = Enter };
            Router = Work.gameObject.AddComponent<ScreenRouter>(); Router.ctx = ctx; ctx.router = Router; Router.Hook();
            Router.Intercept = HandleRoute;

            BuildHandMenu(cam);
            store.Changed += OnStore;
            RebuildRing();
            Router.Go(store.SignedIn ? Route.Dashboard : Route.SignIn, null, _immediate);
        }

        void OnDestroy()
        {
            if (store != null) store.Changed -= OnStore;
            if (_active == this) { _active = null; ThemeManager.SetForced(null); } // a newer hub owns the theme now
        }

        // ---- routing ---------------------------------------------------------------------
        bool HandleRoute(Route route, string id)
        {
            switch (route)
            {
                case Route.Dashboard: case Route.CreateRoom: ShowRing(); return true; // rooms are created on the web, not in the headset
                case Route.Landing: Router.Go(store.SignedIn ? Route.Dashboard : Route.SignIn, null, _immediate); return true;
                case Route.Room:
                    var room = id != null ? store.Get(id) : null;
                    if (room != null && room.phase == Phase.Ready) { ShowRing(); return true; }
                    ShowWork(); return false;
                default: ShowWork(); return false;
            }
        }

        public void ShowRing()
        {
            if (Work != null) Work.gameObject.SetActive(false);
            _ring.gameObject.SetActive(store.SignedIn);
            LayoutRing();
        }

        public void ShowWork()
        {
            _ring.gameObject.SetActive(false);
            Work.gameObject.SetActive(true);
            PlaceWork();
        }

        void PlaceWork() { if (head != null) Work.PlaceInFront(head, 1.6f, -0.05f); }

        /// <summary>Face the ring (and the work panel) the way the viewer is looking now.</summary>
        public void Recenter()
        {
            if (head == null) return;
            _yaw = head.eulerAngles.y; LayoutRing(); if (WorkVisible) PlaceWork();
        }

        // ---- ring ------------------------------------------------------------------------
        List<Room> RingRooms()
        {
            var mine = store.Rooms.ToList();
            return mine.Where(r => RoomLogic.Mine(r)?.status == MemberStatus.Invited).Concat(mine.Where(r => RoomLogic.Mine(r)?.status != MemberStatus.Invited)).ToList();
        }

        void OnStore()
        {
            if (Session != null && Session.State == SessionState.InWorld) return;
            if (!store.SignedIn) { if (RingVisible) { Router.Go(Route.SignIn, null, _immediate); } return; }
            var ids = string.Join(",", RingRooms().Select(r => r.id));
            if (ids != _ringIds) RebuildRing(); else foreach (var c in _cards) c.Refresh(store, Router);
        }

        void RebuildRing()
        {
            foreach (var c in _cards) if (c != null) Destroy(c.gameObject);
            _cards.Clear();
            var rooms = RingRooms(); _ringIds = string.Join(",", rooms.Select(r => r.id));
            foreach (var r in rooms) _cards.Add(PortalCard.Create(_ring, r, store, Router, OnPortal));
            LayoutRing();
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

        void OnPortal(Room room)
        {
            var pres = PortalPresentation.For(room);
            switch (pres.kind)
            {
                case PortalKind.Ready: Enter(room); break;
                case PortalKind.Invited: store.Join(room.id); Router.Go(Route.RoomUpload, room.id, _immediate); break;
                default: Router.OpenRoom(room); break;
            }
        }

        // ---- worlds ----------------------------------------------------------------------
        public void Enter(Room room) { if (Session.State == SessionState.Hub && room.phase == Phase.Ready) _ = Session.EnterAsync(room); }
        public void ExitWorld() { _ = Session.ExitAsync(); }

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
                new HandMenu.Item("home", "Hub", () => { if (Session.State == SessionState.InWorld) ExitWorld(); else Router.Go(Route.Dashboard, null, _immediate); }),
                new HandMenu.Item("pinch", "Recenter", Recenter),
                new HandMenu.Item("moon", "Theme", () => ThemeManager.SetOverride(ThemeManager.Current == ReturnTheme.Dusk ? ReturnTheme.Day : ReturnTheme.Dusk)),
                new HandMenu.Item("play", "Advance", () => { var id = FocusedRoomId(); if (id != null) store.FastForward(id); }),
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

        /// <summary>The room the viewer means: the one on the work panel, or the portal they are facing.</summary>
        public string FocusedRoomId()
        {
            if (WorkVisible && Router.CurrentId != null) return Router.CurrentId;
            if (head == null || _cards.Count == 0) return null;
            var f = head.forward; f.y = 0; f.Normalize();
            return _cards.Where(c => c != null).OrderByDescending(c => Vector3.Dot(f, (c.transform.position - head.position).normalized)).FirstOrDefault()?.roomId;
        }
    }
}
