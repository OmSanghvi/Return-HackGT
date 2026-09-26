using System;
using System.Collections;
using Return.Data;
using Return.Design;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    public enum Route { Landing, SignIn, Dashboard, CreateRoom, RoomUpload, Room }

    /// <summary>What every screen gets: the store, the router and the backdrop.</summary>
    public class AppContext
    {
        public IRoomStore store;
        public ScreenRouter router;
        public IBackdrop backdrop;
        /// <summary>Set by the VR hub: opens the world for a ready room. Null in the flat demo (the Step inside button is hidden).</summary>
        public System.Action<Room> enterWorld;
        public RectTransform panel;
    }

    public abstract class Screen
    {
        protected AppContext app;
        public RectTransform root;
        /// <summary>Build UI into root. Called once on entry.</summary>
        public abstract void Build();
        /// <summary>Store changed. Default: nothing. Override to rebuild (structure changed) or update in place (progress).</summary>
        public virtual void OnStoreChanged() { }
        public virtual void OnExit() { }
        internal void Init(AppContext a, RectTransform r) { app = a; root = r; }
    }

    /// <summary>Replaces react-router: a route stack of one, an auth guard for private routes, and a mist-clearing fade between screens.</summary>
    public class ScreenRouter : MonoBehaviour
    {
        public AppContext ctx;
        public Route Current { get; private set; } = (Route)(-1);
        public string CurrentId { get; private set; }
        public event Action<Route, string> Navigated;
        Screen _screen; Coroutine _running; Route? _pendingRoute; string _pendingId;

        /// <summary>Return true to handle a route yourself (the hub shows its portal ring for Dashboard).</summary>
        public Func<Route, string, bool> Intercept;

        public static bool IsPrivate(Route r) => r != Route.Landing && r != Route.SignIn;

        /// <summary>Go to a route. Private routes redirect to sign-in and come back after.</summary>
        public void Go(Route route, string id = null, bool immediate = false)
        {
            if (IsPrivate(route) && !ctx.store.SignedIn) { _pendingRoute = route; _pendingId = id; route = Route.SignIn; id = null; }
            if (Intercept != null && Intercept(route, id)) return;
            if (immediate) { if (_running != null) StopCoroutine(_running); ShowNow(route, id); return; }
            if (_running != null) StopCoroutine(_running);
            _running = StartCoroutine(Transition(route, id));
        }

        /// <summary>After sign-in: back to where the user was heading.</summary>
        public void ContinueAfterSignIn()
        {
            var r = _pendingRoute ?? Route.Dashboard; var id = _pendingId; _pendingRoute = null; _pendingId = null;
            Go(r, id);
        }

        /// <summary>Open a room where it belongs, from its status.</summary>
        public void OpenRoom(Room r) => Go(RoomLogic.RouteForRoom(r) == RoomLogic.Route.Add ? Route.RoomUpload : Route.Room, r.id);

        Screen Make(Route r)
        {
            switch (r)
            {
                case Route.Landing: return new LandingScreen();
                case Route.SignIn: return new SignInScreen();
                case Route.Dashboard: return new DashboardScreen();
                case Route.CreateRoom: return new CreateRoomScreen();
                case Route.RoomUpload: return new RoomUploadScreen();
                default: return new RoomScreen();
            }
        }

        /// <summary>Synchronous navigation without fades. Used by tests and the screenshot tool.</summary>
        void ShowNow(Route route, string id)
        {
            if (IsPrivate(route) && !ctx.store.SignedIn) { _pendingRoute = route; _pendingId = id; route = Route.SignIn; id = null; }
            if (_screen != null) { _screen.OnExit(); DestroyImmediate(_screen.root.gameObject); _screen = null; }
            Build(route, id);
            _screen.root.GetComponent<CanvasGroup>().alpha = 1;
        }

        IEnumerator Transition(Route route, string id)
        {
            if (_screen != null)
            {
                var old = _screen; yield return Fade(old.root.gameObject, 1, 0, 0.18f);
                old.OnExit(); Destroy(old.root.gameObject); _screen = null;
            }
            Build(route, id);
            yield return Fade(_screen.root.gameObject, 0, 1, ReturnMotion.Base + 0.2f);
            _running = null;
        }

        void Build(Route route, string id)
        {
            // Guards that depend on room state, like the web RoomPage redirects.
            var room = id != null ? ctx.store.Get(id) : null;
            if ((route == Route.Room || route == Route.RoomUpload) && room == null) { route = Route.Dashboard; id = null; room = null; }
            else if (route == Route.Room && room.phase == Phase.Collecting && RoomLogic.Mine(room)?.status != MemberStatus.Done) route = Route.RoomUpload;
            else if (route == Route.RoomUpload && (RoomLogic.Mine(room)?.status == MemberStatus.Done || room.phase != Phase.Collecting)) route = Route.Room;

            Current = route; CurrentId = id;
            var go = UI.Box(ctx.panel, "Screen:" + route); UI.Stretch(go);
            var cg = go.gameObject.AddComponent<CanvasGroup>(); cg.alpha = 0;
            _screen = Make(route); _screen.Init(ctx, go); ((IRouted)_screen).Id = id;
            _screen.Build();
            Navigated?.Invoke(route, id);
            LayoutRebuilder.ForceRebuildLayoutImmediate(go);
        }

        static IEnumerator Fade(GameObject go, float a, float b, float dur)
        {
            var cg = go.GetComponent<CanvasGroup>(); float t = 0;
            while (t < dur && cg != null) { t += Time.unscaledDeltaTime; cg.alpha = Mathf.Lerp(a, b, Mathf.SmoothStep(0, 1, t / dur)); yield return null; }
            if (cg != null) cg.alpha = b;
        }

        void OnEnable() { if (ctx?.store != null) ctx.store.Changed += OnChanged; }
        void OnDisable() { if (ctx?.store != null) ctx.store.Changed -= OnChanged; }
        void OnChanged() { _screen?.OnStoreChanged(); }
        public void Hook() { ctx.store.Changed -= OnChanged; ctx.store.Changed += OnChanged; }
    }

    public interface IRouted { string Id { get; set; } }
}
