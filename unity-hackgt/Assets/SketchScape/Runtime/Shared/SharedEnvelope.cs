// SketchScape SharedEnvelope — one sealed letter as an envelope on the letters desk.
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// Built by SharedRoomLayer. Poke it (hands) or select it with a ray (controllers): the layer asks
// the session to open it. States: sealed (wax seal), openable (soft pulsing glow), opened (flap up).
// A refused open shakes the envelope and says who may open it. Update allocates nothing.
using TMPro;
using UnityEngine;

namespace SketchScape
{
    public class SharedEnvelope : MonoBehaviour
    {
        public string letterId = "";
        public bool canOpen;
        public bool opened;
        public Transform body;          // shaken on refusal
        public Transform flapPivot;     // rotated up when opened
        public GameObject seal;
        public Renderer glow;
        public Color glowColor = Color.white;
        public TextMeshPro hint;
        public string restingHint = "";
        public SharedPokeButton button;

        static readonly int ColorId = Shader.PropertyToID("_Color");
        MaterialPropertyBlock _mpb;
        float _shake;
        float _hintTimer;
        float _flap;          // 0 closed .. 1 open (animated)
        float _phase;

        void Awake()
        {
            _mpb = new MaterialPropertyBlock();
            _flap = opened ? 1f : 0f;
            _phase = Random.value * 6.28f;
            ApplyFlap();
        }

        /// <summary>Wiggle + a short message on the envelope (e.g. "Only Account 2 can open this").</summary>
        public void Refuse(string message)
        {
            _shake = 1f;
            if (hint != null && !string.IsNullOrEmpty(message))
            {
                hint.text = message;
                hint.color = new Color(0.72f, 0.16f, 0.12f);
                _hintTimer = 3f;
            }
        }

        public void ShowOpened()
        {
            opened = true;
            canOpen = false;
            if (seal != null) seal.SetActive(false);
            if (glow != null) glow.enabled = false;
        }

        void ApplyFlap()
        {
            if (flapPivot != null) flapPivot.localRotation = Quaternion.Euler(-172f * _flap, 0f, 0f);
        }

        void Update()
        {
            float dt = Time.unscaledDeltaTime;
            float target = opened ? 1f : 0f;
            if (Mathf.Abs(_flap - target) > 0.001f)
            {
                _flap = Mathf.MoveTowards(_flap, target, dt * 2.2f);
                ApplyFlap();
            }
            if (_shake > 0f && body != null)
            {
                _shake = Mathf.Max(0f, _shake - dt * 2.4f);
                body.localRotation = Quaternion.Euler(0f, 0f, Mathf.Sin(_shake * 40f) * 7f * _shake);
            }
            if (_hintTimer > 0f)
            {
                _hintTimer -= dt;
                if (_hintTimer <= 0f && hint != null)
                {
                    hint.text = restingHint;
                    hint.color = new Color(0.34f, 0.31f, 0.28f);
                }
            }
            if (glow != null && glow.enabled)
            {
                float a = 0.45f + 0.35f * Mathf.Sin(Time.unscaledTime * 2.2f + _phase);
                glow.GetPropertyBlock(_mpb);
                _mpb.SetColor(ColorId, new Color(glowColor.r, glowColor.g, glowColor.b, a));
                glow.SetPropertyBlock(_mpb);
            }
        }
    }
}
