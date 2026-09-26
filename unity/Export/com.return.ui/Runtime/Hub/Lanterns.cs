using System;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// A floating paper lantern: procedural body (scaled sphere, warm flat-shaded material) plus a small billboarded
    /// inner-glow quad. Bobs, and controller tips within ~0.25m bump it with damped velocity (see HubPointers).
    /// Grabbing is XR-only glue (Runtime/XR/XRLanternGrab.cs): it pauses this component's own motion via
    /// SetHeld and calls Release on detach, which floats the lantern up and fades it out before it respawns home.
    /// </summary>
    public class Lantern : MonoBehaviour
    {
        const float BumpRadius = 0.25f, BumpForce = 3.5f, FloatSeconds = 2f, RespawnDelay = 6f;

        /// <summary>Raised for every new lantern. XR glue subscribes to attach an XRGrabInteractable.</summary>
        public static event Action<Lantern> Created;
        public Collider Collider => GetComponent<Collider>();

        Vector3 _home, _offset, _vel;
        float _bobPhase, _floatT = -1f, _nextBumpSound;
        Material _body, _glow;
        bool _held;

        public static Lantern Create(Transform parent, Vector3 home)
        {
            var go = new GameObject("Lantern"); go.transform.SetParent(parent, false); go.transform.position = home;
            var l = go.AddComponent<Lantern>(); l._home = home; l._bobPhase = UnityEngine.Random.value * 5f;

            var body = GameObject.CreatePrimitive(PrimitiveType.Sphere); body.name = "Body"; body.transform.SetParent(go.transform, false);
            body.transform.localScale = new Vector3(0.16f, 0.2f, 0.16f);
            l._body = ReturnShaders.Create(ReturnShaders.Flat);
            l._body.SetColor("_Color", new Color(0.98f, 0.65f, 0.28f, 1f)); l._body.SetFloat("_Radial", 0);
            body.GetComponent<MeshRenderer>().sharedMaterial = l._body;
            var col = body.GetComponent<SphereCollider>(); col.radius = 0.55f; // slightly bigger than the mesh so it's easy to grab

            var glow = new GameObject("Glow"); glow.transform.SetParent(go.transform, false); glow.transform.localScale = Vector3.one * 0.14f;
            glow.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            l._glow = ReturnShaders.Create(ReturnShaders.Flat);
            l._glow.SetColor("_Color", new Color(1f, 0.92f, 0.75f, 0.9f)); l._glow.SetFloat("_Radial", 1);
            glow.AddComponent<MeshRenderer>().sharedMaterial = l._glow;
            glow.AddComponent<Billboard>();

            Created?.Invoke(l);
            return l;
        }

        /// <summary>XR glue calls this on grab/release so this component's own bob/bump/float doesn't fight the interactor's hold.</summary>
        public void SetHeld(bool held) { _held = held; if (!held) Release(); }
        void Release() { _floatT = 0f; }

        void Update()
        {
            if (_held) return;
            if (_floatT >= 0f) { FloatAway(); return; }

            foreach (var p in HubPointers.Points)
            {
                var d = transform.position - p.tip;
                float dist = d.magnitude;
                if (dist < BumpRadius && dist > 0.001f)
                {
                    _vel += d / dist * (BumpRadius - dist) * BumpForce;
                    if (Time.time >= _nextBumpSound) { ReturnAudio.PlayAt(ReturnAudio.LanternBump, transform.position, 0.3f); _nextBumpSound = Time.time + 0.3f; }
                }
            }
            _offset += _vel * Time.deltaTime;
            _vel *= Mathf.Pow(0.05f, Time.deltaTime); // damp fast so it settles, not sloshes forever
            _offset = Vector3.Lerp(_offset, Vector3.zero, Time.deltaTime * 0.4f); // drift back toward home

            var bob = Vector3.up * Mathf.Sin((Time.time + _bobPhase) * Mathf.PI * 2f / 5f) * 0.05f;
            transform.position = _home + _offset + bob;
        }

        void FloatAway()
        {
            _floatT += Time.deltaTime;
            transform.position += Vector3.up * Time.deltaTime * (3f / FloatSeconds) * 0.5f;
            float a = Mathf.Clamp01(1f - _floatT / FloatSeconds);
            SetAlpha(a);
            if (_floatT > RespawnDelay) Respawn(); // respawns ~6s after release, alpha already faded out by FloatSeconds
        }

        void Respawn()
        {
            transform.position = _home; _offset = Vector3.zero; _vel = Vector3.zero; _floatT = -1f;
            SetAlpha(1f);
        }

        void SetAlpha(float a)
        {
            var bc = _body.GetColor("_Color"); bc.a = a; _body.SetColor("_Color", bc);
            var gc = _glow.GetColor("_Color"); gc.a = a * 0.9f; _glow.SetColor("_Color", gc);
        }

        void OnDestroy() { if (_body != null) Destroy(_body); if (_glow != null) Destroy(_glow); }
    }

    /// <summary>4 lanterns floating around the ring, clear of the portal arc (which spans at most 150 deg centered on local +Z) and clear of each other.</summary>
    public static class Lanterns
    {
        static readonly (float angle, float radius, float height)[] Spots =
        {
            (-115f, 2.9f, 1.6f), (115f, 2.9f, 1.6f), (-165f, 2.3f, 1.4f), (165f, 2.3f, 2.0f),
        };

        public static Lantern[] Create(Transform parent)
        {
            var result = new Lantern[Spots.Length];
            for (int i = 0; i < Spots.Length; i++)
            {
                var (angle, radius, height) = Spots[i];
                var dir = Quaternion.Euler(0, angle, 0) * Vector3.forward;
                result[i] = Lantern.Create(parent, dir * radius + Vector3.up * height);
            }
            return result;
        }
    }
}
