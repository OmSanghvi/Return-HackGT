using System.Collections;
using System.Linq;
using NUnit.Framework;
using Return.Data;
using Return.Design;
using UnityEngine;
using UnityEngine.TestTools;

namespace Return.UI.PlayTests
{
    /// <summary>The VR hub in play mode: account picker, portal ring, enter a world, come back. Any logged error fails the test.</summary>
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
        public IEnumerator SignedOut_ShowsPicker_ThenRing()
        {
            yield return null; yield return null;
            var hub = _app.Hub;
            Assert.IsTrue(hub.WorkVisible); Assert.IsFalse(hub.RingVisible);
            string signedInAs = null; hub.SignedIn += n => signedInAs = n;
            var dylanCard = hub.Work.GetComponentsInChildren<Pressable>().First(p => p.name == "Account:" + RoomLogic.MeId);
            dylanCard.onClick();
            yield return Until(() => hub.RingVisible);
            Assert.IsFalse(hub.WorkVisible);
            Assert.AreEqual(4, hub.Cards.Count); // Dylan's 4 ready, joined worlds; the invited ava-graduation room is excluded
            Assert.AreEqual("Dylan Houle", signedInAs);
            Assert.AreEqual(ReturnTheme.Day, ThemeManager.Current);
        }

        [UnityTest]
        public IEnumerator OtherAccount_SeesItsOwnOverlappingReadyRooms()
        {
            yield return null;
            _app.Store.SignIn(RoomLogic.MayaId); _app.Hub.ShowRing();
            yield return Until(() => _app.Hub.RingVisible);
            Assert.AreEqual(3, _app.Hub.Cards.Count);
            CollectionAssert.Contains(_app.Hub.Cards.Select(c => c.roomId).ToList(), "lake-house"); // overlaps with Dylan's rooms
        }

        [UnityTest]
        public IEnumerator EnterReadyPortal_LoadsWorld_AndComesBack()
        {
            yield return null;
            _app.Store.SignIn(); _app.Hub.ShowRing();
            yield return Until(() => _app.Hub.RingVisible);
            Room entering = null; RoomPortal enteringPortal = null;
            _app.Hub.EnteringRoom += (r, p) => { entering = r; enteringPortal = p; };
            var lake = _app.Hub.Cards.First(c => c.roomId == "lake-house");
            lake.portal.Activate();
            Assert.AreEqual("lake-house", entering?.id);
            Assert.AreSame(lake.portal, enteringPortal);
            yield return Until(() => _app.Hub.Session.State == SessionState.InWorld, 8f);
            Assert.IsNotNull(GameObject.Find("World:The lake house"));
            Assert.IsNull(GameObject.Find("ReturnHub"), "hub is hidden inside a world");

            // the wrist Hub button calls the same ExitWorld while in a world
            _app.Hub.ExitWorld();
            yield return Until(() => _app.Hub.Session.State == SessionState.Hub, 8f);
            yield return null;
            Assert.IsNull(GameObject.Find("World:The lake house"));
            Assert.IsTrue(_app.Hub.RingVisible);
            Assert.AreEqual(ReturnTheme.Day, ThemeManager.Current);
        }

        [UnityTest]
        public IEnumerator OnlyReadyJoinedRooms_AppearOnTheRing()
        {
            yield return null;
            _app.Store.SignIn(); _app.Hub.ShowRing();
            yield return Until(() => _app.Hub.RingVisible);
            var ids = _app.Hub.Cards.Select(c => c.roomId).ToList();
            CollectionAssert.DoesNotContain(ids, "ava-graduation"); // still just invited, not ready
            Assert.IsTrue(ids.All(id => _app.Store.Get(id).phase == Phase.Ready));
        }

        [UnityTest]
        public IEnumerator SigningIn_PlaysGreeting_AndBloomsEveryPortalToFullScale()
        {
            yield return null;
            var hub = _app.Hub;
            var dylanCard = hub.Work.GetComponentsInChildren<Pressable>().First(p => p.name == "Account:" + RoomLogic.MeId);
            dylanCard.onClick(); // fires SignedIn, which starts HubIntro's welcome sequence
            yield return Until(() => hub.RingVisible);
            Assert.AreEqual(4, hub.Cards.Count);
            yield return null;
            Assert.IsTrue(hub.Cards.All(c => c.portal.transform.localScale == Vector3.zero), "portals stay hidden during the greeting, then bloom");

            var target = new Vector3(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 1);
            bool AllBloomed() => hub.Cards.All(c => c != null && c.portal != null && Vector3.Distance(c.portal.transform.localScale, target) < 0.01f);
            yield return Until(AllBloomed, 8f); // greeting text (~2.5s) then a staggered bloom per portal
            Assert.IsTrue(AllBloomed());
        }
    }
}
