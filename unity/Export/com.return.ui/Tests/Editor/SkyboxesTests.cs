using System;
using NUnit.Framework;
using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI.Tests
{
    public class SkyboxesTests
    {
        [Test]
        public void FileFor_CoversEverySceneKey()
        {
            foreach (SceneKey k in Enum.GetValues(typeof(SceneKey)))
                Assert.IsFalse(string.IsNullOrEmpty(Skyboxes.FileFor(k)), k + " has no skybox mapped");
        }

        [Test]
        public void FileFor_MatchesTheDesignedMap()
        {
            Assert.AreEqual("sky-kloofendal-48d-partly-cloudy", Skyboxes.FileFor(SceneKey.Hub));
            Assert.AreEqual("sky-evening-meadow", Skyboxes.FileFor(SceneKey.Meadow));
            Assert.AreEqual("sky-kloofendal-48d-partly-cloudy", Skyboxes.FileFor(SceneKey.Plain));
            Assert.AreEqual("sky-citrus-orchard", Skyboxes.FileFor(SceneKey.Clouds));
            Assert.AreEqual("sky-citrus-orchard", Skyboxes.FileFor(SceneKey.CloudSea));
            Assert.AreEqual("sky-kloofendal-38d-partly-cloudy", Skyboxes.FileFor(SceneKey.Beach));
            Assert.AreEqual("sky-kloppenheim-06", Skyboxes.FileFor(SceneKey.Painted));
            Assert.AreEqual("sky-kloppenheim-06", Skyboxes.FileFor(SceneKey.Home));
            Assert.AreEqual("sky-belfast-sunset", Skyboxes.FileFor(SceneKey.Night));
        }

        [Test]
        public void HorizonColorFrom_AveragesTheBandJustAboveTheEquirectHorizonRow()
        {
            // A tiny synthetic equirect: solid blue "sky" for the top half, solid green "ground" for the bottom half.
            // The horizon band sits just above row height/2, so the sampled color should read as sky, not ground.
            var tex = new Texture2D(4, 64, TextureFormat.RGBA32, false);
            var blue = new Color(0.2f, 0.4f, 0.9f, 1f);
            var green = new Color(0.1f, 0.6f, 0.1f, 1f);
            for (int y = 0; y < tex.height; y++)
                for (int x = 0; x < tex.width; x++)
                    tex.SetPixel(x, y, y < tex.height / 2 ? blue : green);
            tex.Apply();

            var horizon = Skyboxes.HorizonColorFrom(tex);
            Assert.AreEqual(blue.r, horizon.r, 0.05f);
            Assert.AreEqual(blue.g, horizon.g, 0.05f);
            Assert.AreEqual(blue.b, horizon.b, 0.05f);

            UnityEngine.Object.DestroyImmediate(tex);
        }

        [Test]
        public void HorizonColorFrom_NullTextureIsWhiteNotAnException()
        {
            Assert.AreEqual(Color.white, Skyboxes.HorizonColorFrom(null));
        }

        // Shader.Find sees every shader in the editor (only a player build strips unreferenced ones), so this also
        // catches a syntax error in SkyboxEquirect.shader that would otherwise only surface as a pink skybox on device.
        [Test]
        public void SkyboxEquirectShader_CompilesAndIsFindable()
        {
            var shader = Shader.Find(ReturnShaders.SkyboxEquirect);
            Assert.IsNotNull(shader, ReturnShaders.SkyboxEquirect + " failed to compile or is missing (Runtime/Shaders/SkyboxEquirect.shader)");
        }
    }
}
