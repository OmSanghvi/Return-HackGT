using System.Collections.Generic;
using UnityEngine;

namespace Return.UI
{
    /// <summary>One controller (or the editor mouse fallback): tip position, forward ray, whether select/trigger is held.</summary>
    public struct HubPointer
    {
        public Vector3 tip, forward;
        public bool select;
    }

    /// <summary>
    /// Live pointer feed for hub ambience (water ripples, firefly repel, lantern bumps). Core assembly holds the list;
    /// Runtime/XR/XRPointerFeed.cs (or the editor mouse fallback) fills it every frame. Empty until something fills it,
    /// which every reader treats as "no pointers this frame".
    /// </summary>
    public static class HubPointers
    {
        static readonly List<HubPointer> _points = new List<HubPointer>();
        public static IReadOnlyList<HubPointer> Points => _points;

        public static void Set(IReadOnlyList<HubPointer> points)
        {
            _points.Clear();
            if (points != null) _points.AddRange(points);
        }

        /// <summary>Where a pointer's forward ray crosses the horizontal plane at height y (default the floor), or null if it doesn't point down at it.</summary>
        public static Vector3? FloorHit(in HubPointer p, float y = 0f)
        {
            if (p.forward.y >= -0.001f) return null;
            float t = (y - p.tip.y) / p.forward.y;
            if (t <= 0f) return null;
            return p.tip + p.forward * t;
        }
    }
}
