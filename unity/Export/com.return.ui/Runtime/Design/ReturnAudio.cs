using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace Return.Design
{
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

        const string Root = "ReturnUI/Audio/";
        const int SpatialPoolSize = 6;

        static readonly Dictionary<string, AudioClip> Cache = new Dictionary<string, AudioClip>();
        static readonly HashSet<string> Warned = new HashSet<string>();

        static Runner _runner;
        static AudioSource _oneShot;
        static AudioSource[] _spatialPool;
        static int _spatialCursor;
        static AudioSource _ambience;

        public static float MasterVolume { get; set; } = 1f;

        static AudioClip Load(string key)
        {
            if (Cache.TryGetValue(key, out var c)) return c;
            c = Resources.Load<AudioClip>(Root + key);
            if (c == null && Warned.Add(key)) Debug.LogWarning("Return UI: missing audio clip " + Root + key);
            Cache[key] = c;
            return c;
        }

        static void EnsureRoot()
        {
            if (_runner != null) return;
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
                src.rolloffMode = AudioRolloffMode.Logarithmic;
                src.minDistance = 0.5f;
                src.maxDistance = 12f;
                src.playOnAwake = false;
                _spatialPool[i] = src;
            }
        }

        public static void Play(string key, float volume = 1f)
        {
            var clip = Load(key);
            if (clip == null) return;
            EnsureRoot();
            _oneShot.PlayOneShot(clip, volume * MasterVolume);
        }

        public static void PlayAt(string key, Vector3 pos, float volume = 1f)
        {
            var clip = Load(key);
            if (clip == null) return;
            EnsureRoot();
            var src = _spatialPool[_spatialCursor];
            _spatialCursor = (_spatialCursor + 1) % _spatialPool.Length;
            src.transform.position = pos;
            src.PlayOneShot(clip, volume * MasterVolume);
        }

        public static AudioSource Loop(string key, Transform parent, float volume, bool spatial)
        {
            var clip = Load(key);
            if (clip == null) return null;
            EnsureRoot();
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

        public static void Ambience(bool on, float fadeSeconds = 2f)
        {
            EnsureRoot();
            const float target = 0.35f;
            if (on)
            {
                if (_ambience == null)
                {
                    _ambience = Loop(AmbienceHub, _runner.transform, 0f, false);
                    if (_ambience == null) return;
                }
                _runner.Fade(_ambience, target * MasterVolume, fadeSeconds, false);
            }
            else if (_ambience != null)
            {
                _runner.Fade(_ambience, 0f, fadeSeconds, true);
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
