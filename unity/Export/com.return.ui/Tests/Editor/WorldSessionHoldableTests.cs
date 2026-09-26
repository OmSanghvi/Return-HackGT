using NUnit.Framework;
using UnityEngine;

namespace Return.UI.Tests
{
    /// <summary>WorldSession.IsHoldable is the one rule the world-interactable pass (Runtime/XR/XRWorldInteractables.cs)
    /// uses to decide what gets a Rigidbody + XRGrabInteractable vs. a static collider: everything under 0.5m on its
    /// largest extent is holdable, consistently, so if one cup is grabbable every cup is.</summary>
    public class WorldSessionHoldableTests
    {
        [Test]
        public void SmallPropsAreHoldable()
        {
            Assert.IsTrue(WorldSession.IsHoldable(new Vector3(0.08f, 0.1f, 0.08f)));  // a mug
            Assert.IsTrue(WorldSession.IsHoldable(new Vector3(0.3f, 0.05f, 0.2f)));   // a book
        }

        [Test]
        public void LargePropsAreNotHoldable()
        {
            Assert.IsFalse(WorldSession.IsHoldable(new Vector3(1.2f, 0.75f, 0.8f)));  // a table
            Assert.IsFalse(WorldSession.IsHoldable(new Vector3(0.6f, 0.02f, 0.02f))); // a long thin plank, largest extent still over the line
        }

        [Test]
        public void TheRuleIsAConsistentThreshold_NotPerObject()
        {
            // Exactly at the line is not holdable (< 0.5, not <=), and the rule only cares about the largest extent.
            Assert.IsFalse(WorldSession.IsHoldable(new Vector3(0.5f, 0.1f, 0.1f)));
            Assert.IsTrue(WorldSession.IsHoldable(new Vector3(0.49f, 0.49f, 0.49f)));
        }
    }
}
