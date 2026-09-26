using Return.UI;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit.Interactables;

namespace Return.UI.XR
{
    /// <summary>Makes every Lantern grabbable: XRGrabInteractable follows the hand exactly (kinematic, no throw);
    /// SetHeld pauses the lantern's own bob/bump while held and its float-away on release.</summary>
    static class XRLanternGrab
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void Init()
        {
            Lantern.Created -= OnLantern; Lantern.Created += OnLantern;
        }

        static void OnLantern(Lantern lantern)
        {
            var go = lantern.gameObject;
            var grab = go.AddComponent<XRGrabInteractable>();
            grab.colliders.Add(lantern.Collider);
            grab.throwOnDetach = false;
            grab.movementType = XRBaseInteractable.MovementType.Kinematic;
            var rb = go.GetComponent<Rigidbody>();
            if (rb != null) { rb.isKinematic = true; rb.useGravity = false; }
            grab.selectEntered.AddListener(_ => lantern.SetHeld(true));
            grab.selectExited.AddListener(_ => lantern.SetHeld(false));
        }
    }
}
