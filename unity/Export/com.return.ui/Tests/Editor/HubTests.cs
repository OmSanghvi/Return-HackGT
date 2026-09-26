using NUnit.Framework;
using Return.Data;
using Return.Design;

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

        [Test]
        public void WorldSceneRoot_ArrivesUnderTheViewer()
        {
            var head = new UnityEngine.GameObject("Head").transform;
            head.SetPositionAndRotation(new UnityEngine.Vector3(2f, 1.6f, -1f), UnityEngine.Quaternion.Euler(10f, 90f, 0f));
            var root = new UnityEngine.GameObject("World Root").AddComponent<WorldSceneRoot>();
            root.buildSky = false;
            var child = new UnityEngine.GameObject("Model").transform; child.SetParent(root.transform, false); child.localPosition = new UnityEngine.Vector3(0, 0, 1.5f);
            try
            {
                root.Arrive(null, head);
                // floor under the head, 1.5 m along the head's yaw (+X at 90 degrees), pitch ignored
                Assert.AreEqual(3.5f, child.position.x, 1e-4f); Assert.AreEqual(0f, child.position.y, 1e-4f);
                Assert.AreEqual(-1f, child.position.z, 1e-4f);
            }
            finally { UnityEngine.Object.DestroyImmediate(root.gameObject); UnityEngine.Object.DestroyImmediate(head.gameObject); }
        }

        // Shader.Find works in the editor for any shader, but a player build only has shaders something references. Each runtime
        // shader needs a template material in Resources/ReturnUI/Shaders or the Quest build strips it and the hub renders black.
        [TestCase("Flat", ReturnShaders.Flat)]
        [TestCase("SkyGradient", ReturnShaders.SkyGradient)]
        [TestCase("SkyParallax", ReturnShaders.SkyParallax)]
        [TestCase("Vignette", ReturnShaders.Vignette)]
        [TestCase("WaterFloor", ReturnShaders.WaterFloor)]
        [TestCase("SkyboxEquirect", ReturnShaders.SkyboxEquirect)]
        [TestCase("ParticlesUnlit", ReturnShaders.ParticlesUnlit)]
        public void RuntimeShaders_HaveBuildTemplates(string template, string shader)
        {
            var m = UnityEngine.Resources.Load<UnityEngine.Material>("ReturnUI/Shaders/" + template);
            Assert.IsNotNull(m, "missing Resources/ReturnUI/Shaders/" + template + ".mat");
            Assert.AreEqual(shader, m.shader.name);
        }
    }
}
