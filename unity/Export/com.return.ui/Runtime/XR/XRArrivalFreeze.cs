using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit.Locomotion;

namespace Return.UI.XR
{
    /// <summary>
    /// Freezes locomotion while the arrival card is up: on WorldSession.MovementLocked(true), disables every enabled
    /// LocomotionProvider in the scene and remembers them; on (false), re-enables just those. No XR-specific code in
    /// WorldSession itself, same pattern as XRInputSupport's RoomPortal/SpatialPanel hooks.
    /// </summary>
    static class XRArrivalFreeze
    {
        static readonly List<LocomotionProvider> _disabled = new List<LocomotionProvider>();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void Init()
        {
            WorldSession.MovementLocked -= OnMovementLocked;
            WorldSession.MovementLocked += OnMovementLocked;
        }

        static void OnMovementLocked(bool locked)
        {
            if (locked) Freeze(); else Unfreeze();
        }

        static void Freeze()
        {
            _disabled.Clear();
            foreach (var p in Object.FindObjectsByType<LocomotionProvider>(FindObjectsSortMode.None))
            {
                if (!p.enabled) continue;
                p.enabled = false;
                _disabled.Add(p);
            }
        }

        static void Unfreeze()
        {
            foreach (var p in _disabled) if (p != null) p.enabled = true;
            _disabled.Clear();
        }
    }
}
