using Return.UI;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactables;
using UnityEngine.XR.Interaction.Toolkit.UI;

namespace Return.UI.XR
{
    /// <summary>
    /// Makes the XR Interaction Toolkit drive the Return UI without the package depending on XR:
    /// every SpatialPanel gets a TrackedDeviceGraphicRaycaster (ray, poke and pinch click glass buttons),
    /// every RoomPortal gets an XRSimpleInteractable (hover brightens it, select activates it).
    /// </summary>
    static class XRInputSupport
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void Init()
        {
            SpatialPanel.Created -= OnPanel; SpatialPanel.Created += OnPanel;
            RoomPortal.Created -= OnPortal; RoomPortal.Created += OnPortal;
        }

        static void OnPanel(SpatialPanel p)
        {
            if (p.GetComponent<TrackedDeviceGraphicRaycaster>() == null) p.gameObject.AddComponent<TrackedDeviceGraphicRaycaster>();
        }

        static void OnPortal(RoomPortal portal)
        {
            var col = portal.GetComponent<Collider>();
            var it = portal.gameObject.AddComponent<XRSimpleInteractable>();
            it.colliders.Add(col);
            it.hoverEntered.AddListener(_ => portal.Hover());
            it.selectEntered.AddListener(_ => portal.Activate());
        }
    }
}
