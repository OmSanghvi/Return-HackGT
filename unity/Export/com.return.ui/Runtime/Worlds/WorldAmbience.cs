using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Looping ambient bed for a world: quiet room tone indoors, an airier wind/water bed outdoors, a couple of spatial
    /// point sources scattered through the world, and a reverb zone sized from its bounds. No CC0 world-ambience clips
    /// ship yet (only the hub's UI/loop clips do), so the bed is filtered noise generated at runtime instead; drop real
    /// clips under Resources/ReturnUI/Audio and load them here the way ReturnAudio does once some exist.
    /// </summary>
    public class WorldAmbience : MonoBehaviour
    {
        const int SampleRate = 22050;
        const float LoopSeconds = 6f;
        static AudioClip _indoorClip, _outdoorClip;

        public static WorldAmbience Build(Transform root, Room room, Bounds bounds)
        {
            if (room == null) return null;
            var go = new GameObject("Ambience");
            go.transform.SetParent(root, false);
            go.transform.position = bounds.center;
            var amb = go.AddComponent<WorldAmbience>();

            bool indoor = room.scene == SceneKey.Home; // ponytail: only one indoor scene key today; widen this when more show up
            var clip = GetClip(indoor);

            var bed = go.AddComponent<AudioSource>();
            bed.clip = clip; bed.loop = true; bed.spatialBlend = 0f; bed.playOnAwake = false;
            bed.volume = 0.18f * ReturnAudio.MasterVolume; bed.Play();

            float horizontalReach = Mathf.Max(bounds.extents.x, bounds.extents.z, 3f);
            int points = bounds.size.x * bounds.size.z > 200f ? 3 : 2;
            for (var i = 0; i < points; i++)
            {
                var src = new GameObject("AmbiencePoint" + i).AddComponent<AudioSource>();
                src.transform.SetParent(go.transform, true);
                src.transform.position = PointIn(bounds, i);
                src.clip = clip; src.loop = true; src.playOnAwake = false;
                src.spatialBlend = 1f; src.spatialize = true;
                src.rolloffMode = AudioRolloffMode.Logarithmic; src.minDistance = 1.5f; src.maxDistance = horizontalReach * 2f;
                src.volume = 0.35f * ReturnAudio.MasterVolume;
                src.Play();
            }

            var reverb = go.AddComponent<AudioReverbZone>();
            reverb.minDistance = Mathf.Max(1f, Mathf.Min(bounds.extents.x, bounds.extents.z));
            reverb.maxDistance = reverb.minDistance + horizontalReach;
            reverb.reverbPreset = indoor ? AudioReverbPreset.Room : AudioReverbPreset.Plain;

            return amb;
        }

        /// <summary>Deterministic-looking spot inside the world's footprint, about head height off its floor.</summary>
        static Vector3 PointIn(Bounds b, int seed)
        {
            var rng = new System.Random(seed * 97 + 13);
            float x = Mathf.Lerp(b.min.x, b.max.x, (float)rng.NextDouble());
            float z = Mathf.Lerp(b.min.z, b.max.z, (float)rng.NextDouble());
            return new Vector3(x, b.min.y + 1.4f, z);
        }

        static AudioClip GetClip(bool indoor)
        {
            if (indoor) return _indoorClip = _indoorClip ?? MakeClip(true);
            return _outdoorClip = _outdoorClip ?? MakeClip(false);
        }

        /// <summary>A short seamless loop of one-pole low-pass-filtered white noise: duller and quieter for an indoor
        /// room tone, airier for an outdoor wind/water bed. ponytail: no distinct bird chirps, just the noise texture;
        /// layer short chirp one-shots via ReturnAudio.PlayAt if the ambience ever needs to read as more than wind.</summary>
        static AudioClip MakeClip(bool indoor)
        {
            int n = Mathf.RoundToInt(SampleRate * LoopSeconds);
            var data = new float[n];
            float lp = 0f;
            float alpha = indoor ? 0.02f : 0.06f;
            float gain = indoor ? 3.2f : 2.0f; // compensates the heavier low-pass losing amplitude
            var rng = new System.Random(indoor ? 1 : 2);
            for (var i = 0; i < n; i++)
            {
                float white = (float)(rng.NextDouble() * 2.0 - 1.0);
                lp += (white - lp) * alpha;
                data[i] = Mathf.Clamp(lp * gain, -1f, 1f);
            }
            int fade = Mathf.Min(n / 20, SampleRate / 4); // fade the seam so the loop doesn't click
            for (var i = 0; i < fade; i++)
            {
                float t = i / (float)fade;
                data[i] *= t; data[n - 1 - i] *= t;
            }
            var clip = AudioClip.Create("WorldAmbience_" + (indoor ? "Indoor" : "Outdoor"), n, 1, SampleRate, false);
            clip.SetData(data, 0);
            return clip;
        }
    }
}
