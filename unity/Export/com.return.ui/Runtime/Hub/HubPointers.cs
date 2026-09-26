using System.Collections.Generic;
using UnityEngine;

namespace Return.UI
{
    /// <summary>One controller (or the editor mouse fallback): tip position, forward ray, whether select/trigger is held,
    /// and the tip's smoothed speed and how long it has been slower than <see cref="HubPointers.StillSpeed"/>.</summary>
    public struct HubPointer
    {
        public Vector3 tip, forward;
        public bool select;
        public float speed, stillFor;
    }

    /// <summary>
    /// Live pointer feed for hub ambience (water ripples, firefly repel/settle, lantern bumps). Core assembly holds the
    /// list; Runtime/XR/XRPointerFeed.cs (or the editor mouse fallback) fills it every frame with tip/forward/select.
    /// Set() fills in speed and stillFor from the previous frame's tip, matched by slot index (stable for the small,
    /// fixed set of hand/controller interactors this feeds from). Empty until something fills it, which every reader
    /// treats as "no pointers this frame".
    /// </summary>
    public static class HubPointers
    {
        /// <summary>Below this speed (m/s) a pointer counts as "still".</summary>
        public const float StillSpeed = 0.05f;
        /// <summary>How long a pointer has to stay still before fireflies drift toward it.</summary>
        public const float StillTime = 1f;
        /// <summary>Above this speed (m/s) a pointer counts as a "fast swing" and scatters fireflies.</summary>
        public const float FastSpeed = 1.5f;

        static readonly List<HubPointer> _points = new List<HubPointer>();
        public static IReadOnlyList<HubPointer> Points => _points;

        // per-slot state carried across frames to smooth speed and time stillness; sized for a couple of hands
        static readonly Vector3[] _prevTip = new Vector3[4];
        static readonly bool[] _hasPrev = new bool[4];
        static readonly float[] _speed = new float[4];
        static readonly float[] _stillFor = new float[4];

        public static void Set(IReadOnlyList<HubPointer> points)
        {
            _points.Clear();
            if (points == null) return;
            float dt = Time.deltaTime;
            for (int i = 0; i < points.Count; i++)
            {
                var p = points[i];
                if (i < _prevTip.Length)
                {
                    float instant = _hasPrev[i] && dt > 0f ? (p.tip - _prevTip[i]).magnitude / dt : 0f;
                    _speed[i] = SmoothSpeed(_speed[i], instant, dt);
                    _stillFor[i] = UpdateStillTimer(_stillFor[i], _speed[i], dt, StillSpeed);
                    p.speed = _speed[i];
                    p.stillFor = _stillFor[i];
                    _prevTip[i] = p.tip;
                    _hasPrev[i] = true;
                }
                _points.Add(p);
            }
        }

        /// <summary>Exponential smoothing toward the instant speed, pure so it can be unit tested. rate is how many
        /// times a second it would fully catch up; clamped so a large dt (or dt == 0) can't overshoot or stall it.</summary>
        public static float SmoothSpeed(float previous, float instant, float dt, float rate = 10f) =>
            Mathf.Lerp(previous, instant, Mathf.Clamp01(dt * rate));

        /// <summary>Runs the still-timer forward while speed stays under threshold, resets it the instant speed crosses it.</summary>
        public static float UpdateStillTimer(float previousTimer, float speed, float dt, float threshold) =>
            speed < threshold ? previousTimer + dt : 0f;

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
