using NUnit.Framework;
using Return.Design;

namespace Return.UI.Tests
{
    /// <summary>The pure stillness/velocity math Fireflies reacts to: smoothing a hand's speed and timing how long
    /// it has stayed under the "still" threshold. Kept as static functions on HubPointers so this can run without
    /// a scene or a frame loop.</summary>
    public class HubPointersTests
    {
        [Test]
        public void SmoothSpeed_MovesTowardInstant_ButNotAllTheWayInOneSmallStep()
        {
            float s = HubPointers.SmoothSpeed(0f, 2f, 0.02f);
            Assert.Greater(s, 0f);
            Assert.Less(s, 2f);
        }

        [Test]
        public void SmoothSpeed_ClampsToInstant_WhenDtIsLarge()
        {
            // a huge or stalled dt shouldn't overshoot past the instant reading
            Assert.AreEqual(2f, HubPointers.SmoothSpeed(0f, 2f, 5f), 1e-5f);
            Assert.AreEqual(0f, HubPointers.SmoothSpeed(5f, 0f, 5f), 1e-5f);
        }

        [Test]
        public void UpdateStillTimer_AccumulatesBelowThreshold_AndResetsAboveIt()
        {
            float timer = 0f;
            timer = HubPointers.UpdateStillTimer(timer, speed: 0.01f, dt: 0.5f, threshold: HubPointers.StillSpeed);
            timer = HubPointers.UpdateStillTimer(timer, speed: 0.01f, dt: 0.5f, threshold: HubPointers.StillSpeed);
            Assert.AreEqual(1f, timer, 1e-5f);
            Assert.GreaterOrEqual(timer, HubPointers.StillTime);

            timer = HubPointers.UpdateStillTimer(timer, speed: 2f, dt: 0.5f, threshold: HubPointers.StillSpeed);
            Assert.AreEqual(0f, timer);
        }

        [Test]
        public void ParticleGlow_HasABuildTemplate()
        {
            // a missing Resources template means the shader gets stripped from a device build and particles draw
            // with whatever pass survives, the square/opaque bug this shader was written to avoid.
            var m = UnityEngine.Resources.Load<UnityEngine.Material>("ReturnUI/Shaders/ParticleGlow");
            Assert.IsNotNull(m, "missing Resources/ReturnUI/Shaders/ParticleGlow.mat");
            Assert.AreEqual(ReturnShaders.ParticleGlow, m.shader.name);
        }
    }
}
