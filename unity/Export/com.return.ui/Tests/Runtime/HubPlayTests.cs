using System.Collections;
using System.Linq;
using NUnit.Framework;
using Return.Data;
using Return.Design;
using UnityEngine;
using UnityEngine.TestTools;

namespace Return.UI.PlayTests
{
    /// <summary>The VR hub in play mode: sign in, portal ring, enter a world, come back. Any logged error fails the test.</summary>
    public class HubPlayTests
    {
        HubApp _app; Transform _head;

        [SetUp]
        public void Setup()
        {
            ThemeManager.SetOverride(null); ThemeManager.SetForced(null);
            var cam = new GameObject("Main Camera", typeof(Camera)) { tag = "MainCamera" }; cam.transform.position = new Vector3(0, 1.6f, 0); _head = cam.transform;
            _app = new GameObject("HubApp").AddComponent<HubApp>(); _app.persist = false; _app.head = _head; _app.fadeSeconds = 0.05f;
        }

        [TearDown] public void Teardown() { Object.Destroy(_app.gameObject); Object.Destroy(_head.gameObject); ThemeManager.SetOverride(null); ThemeManager.SetForced(null); }

        IEnumerator Until(System.Func<bool> c, float timeout = 5f) { float t = 0; while (!c() && t < timeout) { t += Time.unscaledDeltaTime; yield return null; } Assert.IsTrue(c(), "timed out"); }

        [UnityTest]
        public IEnumerator SignedOut_ShowsSignInPanel_ThenRing()
        {
            yield return null; yield return null;
            var hub = _app.Hub;
            Assert.IsTrue(hub.WorkVisible); Assert.IsFalse(hub.RingVisible);
            yield return Until(() => hub.Router.Current == Route.SignIn);
            hub.Work.GetComponentsInChildren<RButton>().First(b => b.label.text == "Continue").press.onClick();
            yield return Until(() => hub.RingVisible);
            Assert.IsFalse(hub.WorkVisible);
            Assert.AreEqual(4, hub.Cards.Count);
            Assert.AreEqual(ReturnTheme.Dusk, ThemeManager.Current);
        }

        [UnityTest]
        public IEnumerator EnterReadyPortal_LoadsWorld_AndComesBack()
        {
            yield return null;
            _app.Store.SignIn(); _app.Hub.Router.ContinueAfterSignIn();
            yield return Until(() => _app.Hub.RingVisible);
            var lake = _app.Hub.Cards.First(c => c.roomId == "lake-house");
            lake.portal.Activate();
            yield return Until(() => _app.Hub.Session.State == SessionState.InWorld, 8f);
            Assert.IsNotNull(GameObject.Find("World:The lake house"));
            Assert.IsNull(GameObject.Find("ReturnHub"), "hub is hidden inside a world");
            _app.Hub.ExitWorld();
            yield return Until(() => _app.Hub.Session.State == SessionState.Hub, 8f);
            yield return null;
            Assert.IsNull(GameObject.Find("World:The lake house"));
            Assert.IsTrue(_app.Hub.RingVisible);
            Assert.AreEqual(ReturnTheme.Dusk, ThemeManager.Current);
        }

        [UnityTest]
        public IEnumerator NotReadyPortals_OpenTheWorkPanel_NotAWorld()
        {
            yield return null;
            _app.Store.SignIn(); _app.Hub.Router.ContinueAfterSignIn();
            yield return Until(() => _app.Hub.RingVisible);
            _app.Hub.Cards.First(c => c.roomId == "last-summer").portal.Activate();      // building
            yield return Until(() => _app.Hub.WorkVisible && _app.Hub.Router.Current == Route.Room);
            Assert.AreEqual(SessionState.Hub, _app.Hub.Session.State);
        }

        [UnityTest]
        public IEnumerator SimulatorFinishesARoom_PortalTurnsReady()
        {
            yield return null;
            _app.Store.SignIn(); _app.Hub.Router.ContinueAfterSignIn();
            yield return Until(() => _app.Hub.RingVisible);
            _app.Store.FastForward("last-summer");
            yield return Until(() => PortalPresentation.For(_app.Store.Get("last-summer")).CanEnter);
        }
    }
}
