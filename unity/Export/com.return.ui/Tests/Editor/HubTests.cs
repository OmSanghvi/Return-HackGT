using System.Linq;
using NUnit.Framework;
using Return.Data;

namespace Return.UI.Tests
{
    public class HubTests
    {
        static Room Seed(string id) => RoomLogic.Seed(1_000_000).First(r => r.id == id);

        [Test]
        public void PortalPresentation_MapsEveryRoomState()
        {
            Assert.AreEqual(PortalKind.Ready, PortalPresentation.For(Seed("lake-house")).kind);
            Assert.IsTrue(PortalPresentation.For(Seed("lake-house")).CanEnter);
            Assert.AreEqual(PortalKind.Waiting, PortalPresentation.For(Seed("grandmas-porch")).kind);
            Assert.AreEqual(PortalKind.Building, PortalPresentation.For(Seed("last-summer")).kind);
            Assert.AreEqual(PortalKind.Invited, PortalPresentation.For(Seed("ava-graduation")).kind);
            Assert.IsFalse(PortalPresentation.For(Seed("last-summer")).CanEnter);
        }

        [Test]
        public void PortalPresentation_FogClearsAsBuildProgresses()
        {
            var r = Seed("last-summer"); r.progress = 0f; var a = PortalPresentation.For(r).mist;
            r.progress = 0.8f; var b = PortalPresentation.For(r).mist;
            Assert.Greater(a, b);
            Assert.AreEqual(0f, PortalPresentation.For(Seed("lake-house")).mist);
        }

        [Test]
        public void AddPhotosPortal_WhenIHaveNotAddedYet()
        {
            var r = Seed("ava-graduation"); RoomLogic.Mine(r).status = MemberStatus.Joined;
            Assert.AreEqual(PortalKind.AddPhotos, PortalPresentation.For(r).kind);
        }

        [Test]
        public void SceneWorldMap_ResolvesMappedRoomsOnly()
        {
            var loader = new SceneWorldLoader(new[] { new WorldEntry { roomId = "lake-house", sceneName = "LakeHouse" }, new WorldEntry { roomId = "", sceneName = "x" } }, new StubWorldLoader());
            Assert.IsTrue(loader.TryGetScene("lake-house", out var s)); Assert.AreEqual("LakeHouse", s);
            Assert.IsFalse(loader.TryGetScene("other", out _));
        }
    }
}
