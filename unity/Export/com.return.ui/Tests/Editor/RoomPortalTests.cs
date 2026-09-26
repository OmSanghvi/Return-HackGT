using NUnit.Framework;
using UnityEngine;

namespace Return.UI.Tests
{
    /// <summary>Pure-logic checks for the portal's head-driven parallax and hum facing weight (RoomPortal.cs).</summary>
    public class RoomPortalTests
    {
        [Test]
        public void HeadOffset_ScalesAndFlipsSign_TowardsOppositeLean()
        {
            var offset = RoomPortal.HeadOffset(new Vector3(0.1f, -0.05f, 0), 1.2f);
            Assert.AreEqual(-0.12f, offset.x, 1e-4f); // leaning right (local +x) shifts the sky left (negative)
            Assert.AreEqual(0.06f, offset.y, 1e-4f);
        }

        [Test]
        public void HeadOffset_ClampsToShaderRange()
        {
            var offset = RoomPortal.HeadOffset(new Vector3(5f, -5f, 0), 1.2f);
            Assert.AreEqual(-0.5f, offset.x);
            Assert.AreEqual(0.5f, offset.y);
        }

        [Test]
        public void HeadOffset_AtOrigin_IsZero()
        {
            Assert.AreEqual(Vector2.zero, RoomPortal.HeadOffset(Vector3.zero, 1.2f));
        }

        [Test]
        public void FacingWeight_IsOne_WhenLookingStraightAtPortal()
        {
            Assert.AreEqual(1f, RoomPortal.FacingWeight(Vector3.forward, Vector3.forward * 3f), 1e-5f);
        }

        [Test]
        public void FacingWeight_IsZero_WhenPortalIsBehindOrToTheSide()
        {
            Assert.AreEqual(0f, RoomPortal.FacingWeight(Vector3.forward, Vector3.right * 3f), 1e-5f); // clamped, not negative
            Assert.Less(RoomPortal.FacingWeight(Vector3.forward, Vector3.back * 3f), 0.01f);
        }
    }
}
