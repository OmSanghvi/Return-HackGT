// SketchScape RoomDirector — runtime reveal and ambience for a RoomKit room.
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// Configured by the Editor RoomKit at build time. On Play it:
//  - reveals non-grabbable objects in order (ease-out scale from ~0, overlapping);
//    grabbable ones stay at full scale (see IsGrabbable),
//  - fades lights and ambient audio up from zero,
//  - plays the narration clip (if any) once the reveal starts,
//  - then keeps a gentle glow pulse and a motif shimmer running.
// Quest-cheap: all arrays are captured in Awake; Update allocates nothing.
using UnityEngine;

namespace SketchScape
{
    [DisallowMultipleComponent]
    public class RoomDirector : MonoBehaviour
    {
        [Header("Reveal")]
        public Transform[] revealTargets = new Transform[0];
        [Min(0.05f)] public float revealSeconds = 1.2f;
        [Range(0f, 0.95f)] public float revealOverlap = 0.45f;
        public float startDelay = 0.6f;
        [Tooltip("Rigidbodies on revealed objects are made kinematic so scanned props stay where the photo put them (they have no support colliders underneath).")]
        public bool keepObjectsKinematic = true;

        [Header("Ambience fade-in")]
        public Light[] fadeLights = new Light[0];
        public AudioSource[] fadeAudio = new AudioSource[0];
        public float fadeSeconds = 2.5f;

        [Header("Narration")]
        public AudioSource narration;
        [TextArea] public string narrationText = "";

        [Header("Staging")]
        public Light glow;
        public float glowPulse = 0.18f;
        public LineRenderer motif;
        public Color moodColor = new Color(1f, 0.75f, 0.5f);

        Vector3[] _targetScales;
        bool[] _keepScale;
        float[] _lightTargets;
        float[] _audioTargets;
        float _glowBase;
        float _start;
        float _stride;
        bool _revealDone;
        bool _fadeDone;
        bool _narrationPlayed;
        Color _motifA, _motifB;

        const float Tiny = 0.001f;

        void Awake()
        {
            int n = revealTargets != null ? revealTargets.Length : 0;
            _targetScales = new Vector3[n];
            _keepScale = new bool[n];
            for (int i = 0; i < n; i++)
            {
                var t = revealTargets[i];
                if (t == null) continue;
                _targetScales[i] = t.localScale;
                _keepScale[i] = IsGrabbable(t);
                if (!_keepScale[i]) t.localScale = _targetScales[i] * Tiny;
                if (keepObjectsKinematic)
                {
                    var body = t.GetComponent<Rigidbody>();
                    if (body != null) { body.isKinematic = true; body.useGravity = false; }
                }
            }

            int l = fadeLights != null ? fadeLights.Length : 0;
            _lightTargets = new float[l];
            for (int i = 0; i < l; i++)
            {
                if (fadeLights[i] == null) continue;
                _lightTargets[i] = fadeLights[i].intensity;
                fadeLights[i].intensity = 0f;
            }

            int a = fadeAudio != null ? fadeAudio.Length : 0;
            _audioTargets = new float[a];
            for (int i = 0; i < a; i++)
            {
                if (fadeAudio[i] == null) continue;
                _audioTargets[i] = fadeAudio[i].volume;
                fadeAudio[i].volume = 0f;
            }

            if (glow != null) _glowBase = glow.intensity;
            if (motif != null) { _motifA = motif.startColor; _motifB = motif.endColor; }
            _stride = revealSeconds * (1f - revealOverlap);
        }

        void Start()
        {
            // Make sure ambient light matches the skybox even without baked lighting data.
            DynamicGI.UpdateEnvironment();
            _start = Time.time + startDelay;
        }

        /// <summary>
        /// Grabbable objects are not scale-revealed. Meta's grab and distance-grab components (Interaction SDK)
        /// record an object's scale when they start and keep putting it back, so an object shrunk for the reveal
        /// in Awake was held at 0.1%: it popped up, then vanished (2026-09-27).
        /// </summary>
        static bool IsGrabbable(Transform t)
        {
            return t.GetComponent<SketchScapePickup>() != null || t.GetComponent("Grabbable") != null;
        }

        /// <summary>Restart the reveal from the beginning (e.g. from a debug button).</summary>
        [ContextMenu("Replay Reveal")]
        public void Replay()
        {
            for (int i = 0; i < _targetScales.Length; i++)
                if (revealTargets[i] != null && !_keepScale[i]) revealTargets[i].localScale = _targetScales[i] * Tiny;
            _revealDone = false;
            _narrationPlayed = false;
            _start = Time.time + startDelay;
        }

        void Update()
        {
            float t = Time.time - _start;
            if (t < 0f) return;

            if (!_narrationPlayed)
            {
                _narrationPlayed = true;
                if (narration != null && narration.clip != null) narration.Play();
            }

            if (!_revealDone)
            {
                bool all = true;
                for (int i = 0; i < _targetScales.Length; i++)
                {
                    var tr = revealTargets[i];
                    if (tr == null || _keepScale[i]) continue;
                    float u = (t - i * _stride) / revealSeconds;
                    if (u < 1f) all = false;
                    tr.localScale = _targetScales[i] * Mathf.Max(Tiny, EaseOutBack(Mathf.Clamp01(u)));
                }
                _revealDone = all;
            }

            if (!_fadeDone)
            {
                float f = Mathf.Clamp01(t / Mathf.Max(0.01f, fadeSeconds));
                float k = f * f * (3f - 2f * f);
                for (int i = 0; i < _lightTargets.Length; i++)
                    if (fadeLights[i] != null && fadeLights[i] != glow) fadeLights[i].intensity = _lightTargets[i] * k;
                for (int i = 0; i < _audioTargets.Length; i++)
                    if (fadeAudio[i] != null) fadeAudio[i].volume = _audioTargets[i] * k;
                if (glow != null) glow.intensity = _glowBase * k;
                _fadeDone = f >= 1f;
            }
            else if (glow != null)
            {
                glow.intensity = _glowBase * (1f + glowPulse * Mathf.Sin(t * 1.3f));
            }

            if (motif != null)
            {
                float s = 0.75f + 0.25f * Mathf.Sin(t * 2.1f);
                float s2 = 0.75f + 0.25f * Mathf.Sin(t * 2.1f + 1.8f);
                motif.startColor = new Color(_motifA.r, _motifA.g, _motifA.b, _motifA.a * s);
                motif.endColor = new Color(_motifB.r, _motifB.g, _motifB.b, _motifB.a * s2);
            }
        }

        static float EaseOutBack(float x)
        {
            const float c1 = 1.2f;
            const float c3 = c1 + 1f;
            float m = x - 1f;
            return 1f + c3 * m * m * m + c1 * m * m;
        }
    }
}
