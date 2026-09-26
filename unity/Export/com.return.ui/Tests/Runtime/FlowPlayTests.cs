using System.Collections;
using System.Linq;
using NUnit.Framework;
using Return.Data;
using Return.Design;
using UnityEngine;
using UnityEngine.TestTools;

namespace Return.UI.PlayTests
{
    /// <summary>Walks the whole room flow by clicking the real UI in play mode. Any logged error or exception fails the test.</summary>
    public class FlowPlayTests
    {
        ReturnApp _app;

        [SetUp]
        public void Setup()
        {
            ThemeManager.SetOverride(ReturnTheme.Day); ThemeManager.SetForced(null);
            var cam = new GameObject("Main Camera", typeof(Camera)) { tag = "MainCamera" };
            cam.transform.position = new Vector3(0, 1.6f, 0);
            var go = new GameObject("ReturnApp");
            _app = go.AddComponent<ReturnApp>(); _app.persist = false; _app.viewer = cam.GetComponent<Camera>(); _app.handMenu = false;
        }

        [TearDown]
        public void Teardown() { Object.Destroy(_app.gameObject); ThemeManager.SetOverride(null); ThemeManager.SetForced(null); }

        RButton Button(string label) => _app.Panel.GetComponentsInChildren<RButton>().First(b => b.label != null && b.label.text == label);
        void Click(string label) => Button(label).press.onClick();
        IEnumerator Until(System.Func<bool> cond, float timeout = 4f) { float t = 0; while (!cond() && t < timeout) { t += Time.unscaledDeltaTime; yield return null; } Assert.IsTrue(cond(), "timed out"); }

        [UnityTest]
        public IEnumerator FullFlow_LandingToReady()
        {
            yield return null; yield return null;
            yield return Until(() => _app.Router != null && _app.Router.Current == Route.Landing);

            // private route redirects to sign in, then continues where the user was heading
            Click("Create a room");
            yield return Until(() => _app.Router.Current == Route.SignIn);
            Click("Continue");
            yield return Until(() => _app.Router.Current == Route.CreateRoom);
            Assert.IsTrue(_app.Store.SignedIn);

            // name required
            Click("Next: add your photos");
            yield return null;
            Assert.AreEqual(Route.CreateRoom, _app.Router.Current);
            var name = _app.Panel.GetComponentsInChildren<RField>().First();
            name.input.text = "Play test room";
            int before = _app.Store.Rooms.Count;
            Click("Invite people later");
            yield return Until(() => _app.Router.Current == Route.RoomUpload);
            Assert.AreEqual(before + 1, _app.Store.Rooms.Count);

            // add photos through the drop zone, then submit
            var drop = _app.Panel.GetComponentsInChildren<Pressable>().First(p => p.name == "Drop");
            drop.onClick();
            yield return null;
            Click("Add to the room");
            yield return Until(() => _app.Router.Current == Route.Room, 5f);
            var room = _app.Store.Get(_app.Router.CurrentId);
            Assert.AreEqual(MemberStatus.Done, RoomLogic.Mine(room).status);
            Assert.AreEqual(3, room.photos.Count);

            // a seeded building room advances to ready with Dusk forced, and clears it on exit
            _app.Router.Go(Route.Room, "last-summer");
            yield return Until(() => _app.Router.CurrentId == "last-summer");
            yield return null;
            _app.FastForward();
            yield return Until(() => _app.Store.Get("last-summer").phase == Phase.Ready);
            yield return Until(() => ThemeManager.Current == ReturnTheme.Dusk);
            _app.Router.Go(Route.Dashboard);
            yield return Until(() => _app.Router.Current == Route.Dashboard);
            yield return Until(() => ThemeManager.Current == ReturnTheme.Day);
        }

        [UnityTest]
        public IEnumerator Simulator_FinishesACollectingRoom()
        {
            yield return null;
            _app.Store.SignIn();
            _app.Router.Go(Route.Room, "grandmas-porch");
            yield return Until(() => _app.Router.CurrentId == "grandmas-porch");
            yield return null;
            _app.FastForward();                                   // Sam arrives, everyone is in
            yield return Until(() => _app.Store.Get("grandmas-porch").phase == Phase.Building);
            _app.FastForward();
            yield return Until(() => _app.Store.Get("grandmas-porch").phase == Phase.Ready);
        }

        [UnityTest]
        public IEnumerator Dashboard_ManageSheetsOpenAndClose()
        {
            yield return null;
            _app.Store.SignIn();
            _app.Router.Go(Route.Dashboard);
            yield return Until(() => _app.Router.Current == Route.Dashboard);
            yield return null;
            int rooms = _app.Store.Rooms.Count;
            var manage = _app.Panel.GetComponentsInChildren<Pressable>().First(p => p.name == "Manage");
            manage.onClick();
            yield return null;
            Assert.IsNotNull(_app.Panel.GetComponentInChildren<Sheet>());

            Click("Manage people");                       // opens the people sheet, closes the menu
            yield return null; yield return null;
            Assert.AreEqual(1, _app.Panel.GetComponentsInChildren<Sheet>().Length);
            _app.Panel.GetComponentInChildren<Sheet>().Close();
            yield return null;

            _app.Panel.GetComponentsInChildren<Pressable>().First(p => p.name == "Manage").onClick();
            yield return null;
            Click("Delete room");                         // confirm sheet
            yield return null; yield return null;
            Click("Keep it");
            yield return null; yield return null;
            Assert.AreEqual(rooms, _app.Store.Rooms.Count);

            _app.Panel.GetComponentsInChildren<Pressable>().First(p => p.name == "Manage").onClick();
            yield return null;
            Click("Delete room"); yield return null; yield return null;
            Click("Delete room");                         // the danger button in the confirm sheet
            yield return null;
            Assert.AreEqual(rooms - 1, _app.Store.Rooms.Count);
        }
    }
}
