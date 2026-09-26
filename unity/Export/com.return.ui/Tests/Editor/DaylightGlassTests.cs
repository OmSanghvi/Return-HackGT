using NUnit.Framework;
using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI.Tests
{
    public class DaylightGlassTests
    {
        [Test]
        public void DefaultScene_PicksDayMeadowOrDuskHub()
        {
            Assert.AreEqual(SceneKey.Meadow, HubEnvironment.DefaultScene(false));
            Assert.AreEqual(SceneKey.Hub, HubEnvironment.DefaultScene(true));
        }

        // Shader.Find sees every shader in the editor (only a player build strips unreferenced ones), so this also
        // catches a syntax error in LiquidGlass.shader that would otherwise only surface as a pink material on device.
        [Test]
        public void LiquidGlassShader_CompilesAndIsFindable()
        {
            var mat = UIAssets.LiquidGlass();
            Assert.IsNotNull(mat, "Return/LiquidGlass shader failed to compile or is missing (Runtime/Shaders/LiquidGlass.shader)");
            Object.DestroyImmediate(mat);
        }
    }
}
