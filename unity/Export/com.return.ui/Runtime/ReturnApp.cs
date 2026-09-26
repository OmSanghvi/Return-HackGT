using Return.Data;
using Return.Design;
using UnityEngine;
using UnityEngine.EventSystems;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
#endif

namespace Return.UI
{
    /// <summary>
    /// Drop this on an empty GameObject: it builds the sky backdrop, the main world-space panel, the router, the hand menu and the demo simulator.
    /// Portable: needs a camera, URP and the package. XR rigs add their own ray/poke input on top (TrackedDeviceGraphicRaycaster).
    /// </summary>
    public class ReturnApp : MonoBehaviour
    {
        [Header("Placement")]
        public Camera viewer;
        public float panelWidthDp = 1360, panelHeightDp = 860;
        public float distance = ReturnSpatial.PanelDistanceRay + 0.5f;

        [Header("Behaviour")]
        public Route startRoute = Route.Landing;
        [Tooltip("Off = rooms live in memory only.")] public bool persist = true;
        [Tooltip("'.' fast-forwards the open room (demo). The hand menu button does the same.")] public bool demoSimulator = true;
        public bool handMenu = true;

        public IRoomStore Store { get; private set; }
        public ScreenRouter Router { get; private set; }
        public SkyBackdrop Backdrop { get; private set; }
        public SpatialPanel Panel { get; private set; }

        bool _booted;

        void Start() { Bootstrap(); }

        /// <summary>Build everything. Runs from Start; call manually in edit mode (tools, tests).</summary>
        public void Bootstrap()
        {
            if (_booted) return; _booted = true;
            if (viewer == null) viewer = Camera.main;
            EnsureEventSystem();

            Store = new RoomStore(persist ? RoomStore.DefaultPath : null);
            if (Application.isPlaying && Application.absoluteURL != null && Application.absoluteURL.Contains("?reset")) Store.Reset();

            var sky = new GameObject("ReturnSky"); sky.transform.SetParent(transform, false);
            Backdrop = sky.AddComponent<SkyBackdrop>();
            Backdrop.distance = distance + 3.5f; Backdrop.size = new Vector2(13f, 7.3f);

            Panel = SpatialPanel.Create("ReturnPanel", panelWidthDp, panelHeightDp, transform);
            if (viewer != null) { Panel.PlaceInFront(viewer.transform, distance, 0f); Panel.SetEventCamera(viewer); }

            var ctx = new AppContext { store = Store, backdrop = Backdrop, panel = Panel.rect };
            Router = Panel.gameObject.AddComponent<ScreenRouter>(); Router.ctx = ctx; ctx.router = Router; Router.Hook();

            if (handMenu) BuildHandMenu();
            Router.Go(startRoute, null, !Application.isPlaying);
        }

        void BuildHandMenu()
        {
            var p = SpatialPanel.Create("ReturnHandMenu", 420, 110, transform);
            if (viewer != null) { p.PlaceInFront(viewer.transform, distance - 0.15f, -0.52f); p.SetEventCamera(viewer); p.transform.Rotate(20, 0, 0); }
            var m = HandMenu.Create(p.rect, new[]
            {
                new HandMenu.Item("home", "Rooms", () => Router.Go(Store.SignedIn ? Route.Dashboard : Route.Landing)),
                new HandMenu.Item("play", "Advance", FastForward),
                new HandMenu.Item("moon", "Theme", () => ThemeManager.SetOverride(ThemeManager.Current == ReturnTheme.Dusk ? ReturnTheme.Day : ReturnTheme.Dusk)),
                new HandMenu.Item("refresh", "Reset demo", () => { Store.Reset(); Router.Go(Route.Landing); }),
            });
            UI.Anchor(m, new Vector2(0.5f, 0.5f), Vector2.zero);
        }

        /// <summary>Demo fast-forward: one visible step for the open room.</summary>
        public void FastForward()
        {
            if (!demoSimulator || Router == null || Router.CurrentId == null) return;
            Store.FastForward(Router.CurrentId);
        }

        void Update()
        {
            if (Store == null) return;
            Store.Step(Time.unscaledDeltaTime);
#if ENABLE_INPUT_SYSTEM
            if (demoSimulator && Keyboard.current != null && Keyboard.current.periodKey.wasPressedThisFrame) FastForward();
#endif
        }

        static void EnsureEventSystem() { UIEventSystem.Ensure(); }
    }
}
