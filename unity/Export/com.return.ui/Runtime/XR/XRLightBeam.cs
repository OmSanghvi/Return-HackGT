using System.Collections.Generic;
using System.Linq;
using Return.Design;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.Interactors.Visuals;

namespace Return.UI.XR
{
    /// <summary>
    /// Replaces XRI's default hard ray line on every ray/near-far interactor (the same ones XRPointerFeed finds) with a
    /// soft beam: a thin LineRenderer that tapers and fades to 0 alpha at the tip, plus a small glow dot where it hits
    /// something. The default XRInteractorLineVisual is disabled rather than removed, so it comes back for free if this
    /// ever needs to be turned off per-interactor.
    /// </summary>
    static class XRLightBeam
    {
        const float Width = 0.006f, GlowSize = 0.03f, DefaultLength = 3f;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Init()
        {
            if (GameObject.Find("XRLightBeam") != null) return;
            var go = new GameObject("XRLightBeam");
            Object.DontDestroyOnLoad(go);
            go.AddComponent<Runner>();
        }

        static Color Warm => (Color)(ThemeManager.Current == ReturnTheme.Dusk ? ReturnColorsDusk.Sun : ReturnColorsDay.Sun);

        class Runner : MonoBehaviour
        {
            readonly List<Beam> _beams = new List<Beam>();
            IXRRayProvider[] _rays = System.Array.Empty<IXRRayProvider>();
            float _rescanAt;

            void OnEnable() { SceneManager.sceneLoaded += OnSceneLoaded; Rescan(); }
            void OnDisable() { SceneManager.sceneLoaded -= OnSceneLoaded; }
            void OnSceneLoaded(Scene s, LoadSceneMode m) => Rescan();

            void Rescan()
            {
                foreach (var b in _beams) b.Destroy();
                _beams.Clear();
                _rays = Object.FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None).OfType<IXRRayProvider>().ToArray();
                foreach (var ray in _rays) _beams.Add(Beam.Create((MonoBehaviour)ray));
            }

            void Update()
            {
                // controllers can spawn a frame or two after scene load, same as XRPointerFeed; keep looking until found
                if (_rays.Length == 0 && Time.unscaledTime > _rescanAt) { _rescanAt = Time.unscaledTime + 1f; Rescan(); }
                for (int i = 0; i < _rays.Length; i++)
                {
                    var mb = _rays[i] as MonoBehaviour;
                    if (mb == null || !mb.isActiveAndEnabled) { _beams[i].SetVisible(false); continue; }
                    _beams[i].Refresh(_rays[i]);
                }
            }
        }

        class Beam
        {
            LineRenderer _line; Transform _glow; Material _glowMat;

            public static Beam Create(MonoBehaviour owner)
            {
                var lineVisual = owner.GetComponent<XRInteractorLineVisual>();
                if (lineVisual != null) lineVisual.enabled = false; // the hard default line; we draw our own soft one instead

                var go = new GameObject("SoftBeam"); go.transform.SetParent(owner.transform, false);
                var lr = go.AddComponent<LineRenderer>();
                lr.positionCount = 2; lr.useWorldSpace = true;
                lr.widthCurve = new AnimationCurve(new Keyframe(0, Width), new Keyframe(1, 0f));
                lr.numCapVertices = 4;
                var warm = Warm;
                lr.colorGradient = new Gradient
                {
                    colorKeys = new[] { new GradientColorKey(warm, 0f), new GradientColorKey(warm, 1f) },
                    alphaKeys = new[] { new GradientAlphaKey(0.85f, 0f), new GradientAlphaKey(0f, 1f) },
                };
                lr.material = Shapes.ParticleMaterial(false);
                lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; lr.receiveShadows = false;

                var glow = new GameObject("Tip"); glow.transform.SetParent(go.transform, false);
                glow.transform.localScale = Vector3.one * GlowSize;
                glow.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
                var glowMat = ReturnShaders.Create(ReturnShaders.Flat);
                glowMat.SetColor("_Color", new Color(warm.r, warm.g, warm.b, 0.85f)); glowMat.SetFloat("_Radial", 1);
                glow.AddComponent<MeshRenderer>().sharedMaterial = glowMat;
                glow.AddComponent<Billboard>();

                return new Beam { _line = lr, _glow = glow.transform, _glowMat = glowMat };
            }

            public void SetVisible(bool v) { if (_line != null) _line.enabled = v; if (_glow != null) _glow.gameObject.SetActive(v); }

            public void Refresh(IXRRayProvider ray)
            {
                var origin = ray.GetOrCreateRayOrigin();
                if (origin == null) { SetVisible(false); return; }
                SetVisible(true);
                var end = ray.rayEndTransform != null ? ray.rayEndPoint : origin.position + origin.forward * DefaultLength;
                _line.SetPosition(0, origin.position); _line.SetPosition(1, end);
                bool hit = ray.rayEndTransform != null;
                _glow.gameObject.SetActive(hit);
                if (hit) _glow.position = end;
            }

            public void Destroy()
            {
                if (_line != null) Object.Destroy(_line.gameObject);
                if (_glowMat != null) Object.Destroy(_glowMat);
            }
        }
    }
}
