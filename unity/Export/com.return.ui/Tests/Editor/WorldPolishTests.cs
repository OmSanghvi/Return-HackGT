using NUnit.Framework;
using UnityEngine;

namespace Return.UI.Tests
{
    /// <summary>Pure-function checks for the world polish pass (WorldLife's name matcher, ContactShadow's footprint sizing);
    /// everything else in that pass needs a scene, so it's covered by the existing PlayMode/manual capture loop instead.</summary>
    public class WorldPolishTests
    {
        [TestCase("tree_oak", true)]
        [TestCase("Curtain_Long", true)]
        [TestCase("loungeChair", false)]
        [TestCase("", false)]
        [TestCase(null, false)]
        public void IsFoliageName_MatchesFoliageAndClothWords(string name, bool expected) =>
            Assert.AreEqual(expected, WorldLife.IsFoliageName(name));

        [TestCase("campfire_stones", true)]
        [TestCase("Lantern", true)]
        [TestCase("rock_largeA", false)]
        [TestCase("", false)]
        public void IsFlickerName_MatchesCandleLampFireWords(string name, bool expected) =>
            Assert.AreEqual(expected, WorldLife.IsFlickerName(name));

        [Test]
        public void ContactShadow_Radius_ScalesWithTheLargerFootprintDimension()
        {
            float r = ContactShadow.Radius(new Vector3(2f, 3f, 1f));
            Assert.AreEqual(2f * 0.5f * 1.15f, r, 1e-4f); // padded a bit beyond the prop's own footprint

            Assert.Greater(ContactShadow.Radius(new Vector3(4f, 0f, 1f)), ContactShadow.Radius(new Vector3(1f, 0f, 1f)));
        }
    }
}
