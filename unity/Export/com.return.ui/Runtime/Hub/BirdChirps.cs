using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Daytime hub only: every 6 to 14s, a single bird_chirp plays from a random point on a ring around the viewer,
    /// through ReturnAudio's spatial pool. Lives under HubEnvironment's "Environment" root, so it starts and stops
    /// with that object's enabled state the same way the hub ambience bed does: active in the hub, paused (root
    /// deactivated) while a world is loaded.
    /// </summary>
    public class BirdChirps : MonoBehaviour
    {
        const float MinGap = 6f, MaxGap = 14f, MinRadius = 5f, MaxRadius = 8f, MinHeight = 2f, MaxHeight = 5f;
        const float MinPitch = 0.9f, MaxPitch = 1.15f, Volume = 0.22f;

        Transform _head;
        float _next;

        public static BirdChirps Create(Transform parent)
        {
            var go = new GameObject("BirdChirps"); go.transform.SetParent(parent, false);
            var b = go.AddComponent<BirdChirps>();
            b._next = Time.time + Random.Range(MinGap, MaxGap);
            return b;
        }

        void Update()
        {
            if (_head == null && Camera.main != null) _head = Camera.main.transform;
            if (Time.time < _next) return;
            _next = Time.time + Random.Range(MinGap, MaxGap);
            var origin = _head != null ? _head.position : transform.position;
            var angle = Random.Range(0f, 360f) * Mathf.Deg2Rad;
            var radius = Random.Range(MinRadius, MaxRadius);
            var pos = origin + new Vector3(Mathf.Sin(angle) * radius, Random.Range(MinHeight, MaxHeight), Mathf.Cos(angle) * radius);
            ReturnAudio.PlayAt(ReturnAudio.BirdChirp, pos, Volume, Random.Range(MinPitch, MaxPitch));
        }
    }
}
