using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace Return.Design
{
    /// <summary>Which procedural bed a portal's hum should use, matched to the room's scene key.</summary>
    public enum Ambience { Water, Wind }

    /// <summary>Ambient audio bed for the Return hub: loads clips from Resources/ReturnUI/Audio, pools sources, fades the ambience loop.</summary>
    public static class ReturnAudio
    {
        public const string AmbienceHub = "ambience_hub";
        public const string PortalHum = "portal_hum";
        public const string UiHover = "ui_hover";
        public const string UiSelect = "ui_select";
        public const string Chime = "chime";
        public const string WhooshIn = "whoosh_in";
        public const string WhooshOut = "whoosh_out";
        public const string GreetingSwell = "greeting_swell";
        public const string LanternBump = "lantern_bump";
        public const string Ripple = "ripple";
        public const string PianoBed = "piano_bed";

        const string Root = "ReturnUI/Audio/";
        const int SpatialPoolSize = 6;

        static readonly Dictionary<string, AudioClip> Cache = new Dictionary<string, AudioClip>();
        static readonly HashSet<string> Warned = new HashSet<string>();
        static readonly Dictionary<Ambience, AudioClip> ProceduralCache = new Dictionary<Ambience, AudioClip>();

        static Runner _runner;
        static AudioSource _oneShot;
        static AudioSource[] _spatialPool;
        static int _spatialCursor;
        static AudioSource _ambience, _piano;

        public static float MasterVolume { get; set; } = 1f;

        static AudioClip Load(string key)
        {
            if (Cache.TryGetValue(key, out var c)) return c;
            c = Resources.Load<AudioClip>(Root + key);
            if (c == null && Warned.Add(key)) Debug.LogWarning("Return UI: missing audio clip " + Root + key);
            Cache[key] = c;
            return c;
        }

        static bool _quitting;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            _quitting = false;
            Application.quitting -= OnQuitting;
            Application.quitting += OnQuitting;
        }

        static void OnQuitting() => _quitting = true;

        /// <summary>False while the app/play mode is shutting down, so teardown callbacks (OnDisable) never spawn a new root.</summary>
        static bool EnsureRoot()
        {
            if (_runner != null) return true;
            if (_quitting) return false;
            var go = new GameObject("ReturnAudio");
            Object.DontDestroyOnLoad(go);
            _runner = go.AddComponent<Runner>();

            _oneShot = go.AddComponent<AudioSource>();
            _oneShot.spatialBlend = 0f;
            _oneShot.playOnAwake = false;

            _spatialPool = new AudioSource[SpatialPoolSize];
            for (var i = 0; i < SpatialPoolSize; i++)
            {
                var child = new GameObject("SpatialVoice" + i);
                child.transform.SetParent(go.transform);
                var src = child.AddComponent<AudioSource>();
                src.spatialBlend = 1f;
                src.spatialize = true; // HRTF spatializer plugin, installed elsewhere; positional SFX (portal touch, ripples, bumps) get it for free
                src.rolloffMode = AudioRolloffMode.Logarithmic;
                src.minDistance = 0.5f;
                src.maxDistance = 12f;
                src.playOnAwake = false;
                _spatialPool[i] = src;
            }
            return true;
        }

        public static void Play(string key, float volume = 1f)
        {
            var clip = Load(key);
            if (clip == null || !EnsureRoot()) return;
            _oneShot.PlayOneShot(clip, volume * MasterVolume);
        }

        public static void PlayAt(string key, Vector3 pos, float volume = 1f)
        {
            var clip = Load(key);
            if (clip == null || !EnsureRoot()) return;
            var src = _spatialPool[_spatialCursor];
            _spatialCursor = (_spatialCursor + 1) % _spatialPool.Length;
            src.transform.position = pos;
            src.PlayOneShot(clip, volume * MasterVolume);
        }

        public static AudioSource Loop(string key, Transform parent, float volume, bool spatial)
        {
            var clip = Load(key);
            if (clip == null || !EnsureRoot()) return null;
            var go = new GameObject("Loop_" + key);
            go.transform.SetParent(parent, false);
            var src = go.AddComponent<AudioSource>();
            src.clip = clip;
            src.loop = true;
            src.spatialBlend = spatial ? 1f : 0f;
            src.rolloffMode = AudioRolloffMode.Logarithmic;
            src.minDistance = 0.5f;
            src.maxDistance = 12f;
            src.volume = volume * MasterVolume;
            src.Play();
            return src;
        }

        /// <summary>Which procedural bed matches a room's painted scene: water for lake/beach scenes, wind everywhere else (plains, clouds, sky).</summary>
        public static Ambience AmbienceFor(Return.Data.SceneKey scene)
        {
            switch (scene)
            {
                case Return.Data.SceneKey.Meadow:
                case Return.Data.SceneKey.Night:
                case Return.Data.SceneKey.Beach:
                    return Ambience.Water;
                default:
                    return Ambience.Wind;
            }
        }

        /// <summary>Short looping bed of filtered noise for portal hums: no sourced clip is scene-specific yet, so this generates one
        /// (low-pass rumble for water, brighter hiss with slow gusts for wind), the same way portal_hum/whoosh were made (in-house
        /// synthesis, see THIRD-PARTY.md). Generated once per kind and cached.</summary>
        public static AudioClip ProceduralAmbience(Ambience kind)
        {
            if (ProceduralCache.TryGetValue(kind, out var cached) && cached != null) return cached;
            const int sampleRate = 22050;
            const float seconds = 4f;
            int n = (int)(sampleRate * seconds);
            var data = new float[n];
            var rng = new System.Random(kind == Ambience.Water ? 917 : 419);
            float lp = 0f;
            float alpha = kind == Ambience.Water ? 0.05f : 0.18f;
            for (int i = 0; i < n; i++)
            {
                float white = (float)(rng.NextDouble() * 2.0 - 1.0);
                lp += alpha * (white - lp);
                float gust = kind == Ambience.Wind ? 0.65f + 0.35f * Mathf.Sin(2f * Mathf.PI * 0.09f * i / sampleRate) : 1f;
                data[i] = lp * gust;
            }
            int fade = Mathf.Min(sampleRate / 4, n / 4); // crossfade the tail into the head so the loop point doesn't click
            for (int i = 0; i < fade; i++)
            {
                float t = i / (float)fade;
                data[n - fade + i] = Mathf.Lerp(data[n - fade + i], data[i], t);
            }
            var clip = AudioClip.Create("ProceduralAmbience_" + kind, n, 1, sampleRate, false);
            clip.SetData(data, 0);
            ProceduralCache[kind] = clip;
            return clip;
        }

        /// <summary>A dedicated looping 3D source for a portal's room hum: quiet, HRTF-spatialized, rolls off between 1 m and 6 m so
        /// it fades out well before the next portal on the ring. Not pooled: portals are few and live for the hub's lifetime.</summary>
        public static AudioSource PortalHumSource(Transform parent, Return.Data.SceneKey scene, float volume)
        {
            var go = new GameObject("PortalHum");
            go.transform.SetParent(parent, false);
            var src = go.AddComponent<AudioSource>();
            src.clip = ProceduralAmbience(AmbienceFor(scene));
            src.loop = true; src.playOnAwake = false;
            src.spatialBlend = 1f; src.spatialize = true;
            src.rolloffMode = AudioRolloffMode.Logarithmic;
            src.minDistance = 1f; src.maxDistance = 6f;
            src.volume = volume * MasterVolume;
            src.Play();
            return src;
        }

        public static void Ambience(bool on, float fadeSeconds = 2f)
        {
            // Fading out never needs a new root: if it's gone (scene teardown, quitting) there is nothing playing.
            if (on ? !EnsureRoot() : _runner == null) return;
            FadeBed(ref _ambience, AmbienceHub, 0.2f, on, fadeSeconds);
            FadeBed(ref _piano, PianoBed, 0.12f, on, fadeSeconds);
        }

        static void FadeBed(ref AudioSource src, string key, float target, bool on, float fadeSeconds)
        {
            if (on)
            {
                if (src == null) src = Loop(key, _runner.transform, 0f, false);
                if (src == null) return;
                if (!src.isPlaying) src.Play();
                _runner.Fade(src, target * MasterVolume, fadeSeconds, false);
            }
            else if (src != null)
            {
                _runner.Fade(src, 0f, fadeSeconds, true);
            }
        }

        class Runner : MonoBehaviour
        {
            public void Fade(AudioSource src, float to, float duration, bool stopAtEnd) => StartCoroutine(FadeCo(src, to, duration, stopAtEnd));

            static IEnumerator FadeCo(AudioSource src, float to, float duration, bool stopAtEnd)
            {
                var from = src.volume;
                var t = 0f;
                while (t < duration)
                {
                    t += Time.deltaTime;
                    src.volume = Mathf.Lerp(from, to, duration <= 0f ? 1f : t / duration);
                    yield return null;
                }
                src.volume = to;
                if (stopAtEnd) src.Stop();
            }
        }
    }
}
