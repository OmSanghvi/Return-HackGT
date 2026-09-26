using NUnit.Framework;
using Return.Data;

namespace Return.UI.Tests
{
    public class HubTests
    {
        [Test]
        public void SceneWorldMap_ResolvesMappedRoomsOnly()
        {
            var loader = new SceneWorldLoader(new[] { new WorldEntry { roomId = "lake-house", sceneName = "LakeHouse" }, new WorldEntry { roomId = "", sceneName = "x" } }, new StubWorldLoader());
            Assert.IsTrue(loader.TryGetScene("lake-house", out var s)); Assert.AreEqual("LakeHouse", s);
            Assert.IsFalse(loader.TryGetScene("other", out _));
        }
    }
}
