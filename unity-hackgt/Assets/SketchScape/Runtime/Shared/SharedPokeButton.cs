// SketchScape SharedPokeButton — a physical button face for hands (poke) and controllers (ray).
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// The button's own transform is the face: local z = 0, facing -Z (towards the viewer), size in
// local x/y. Setup() adds the Meta Interaction SDK pieces the rig's interactors look for: a
// PlaneSurface clipped to the face (ClippedPlaneSurface + BoundsClipper), a PokeInteractable
// (hand / controller poke) and a RayInteractable (controller ray, hand ray) on that surface.
// Selecting either raises Pressed. Press() does the same from code (tests, other scripts).
// Update only animates a press depth and hover highlight; it allocates nothing.
using System;
using Oculus.Interaction;
using Oculus.Interaction.Surfaces;
using UnityEngine;

namespace SketchScape
{
    [DisallowMultipleComponent]
    public class SharedPokeButton : MonoBehaviour
    {
        public Vector2 size = new Vector2(0.12f, 0.07f);
        [Tooltip("Moved in along +Z while pressed.")]
        public Transform visual;
        [Tooltip("Shown while a hand or ray hovers the button.")]
        public GameObject hoverHighlight;
        public float pressDepth = 0.008f;
        [Tooltip("Free text for the owner (account id, letter id).")]
        public string payload = "";
        public float cooldownSeconds = 0.4f;

        public event Action<SharedPokeButton> Pressed;
        public bool Hovered { get; private set; }

        PokeInteractable _poke;
        RayInteractable _ray;
        Vector3 _visualRest;
        bool _restCaptured;
        float _pressPulse;
        float _lastPress = -10f;
        bool _selected;

        /// <summary>Adds the surface and interactables (idempotent). Call before the button is first activated.</summary>
        public void Setup()
        {
            if (GetComponentInChildren<PokeInteractable>(true) != null) return;
            var surfaceGo = new GameObject("Surface");
            surfaceGo.transform.SetParent(transform, false);
            var plane = surfaceGo.AddComponent<PlaneSurface>();   // default facing: -Z, towards the viewer
            var clipper = surfaceGo.AddComponent<BoundsClipper>();
            clipper.Position = Vector3.zero;
            clipper.Size = new Vector3(Mathf.Max(0.01f, size.x), Mathf.Max(0.01f, size.y), 0.03f);
            var clipped = surfaceGo.AddComponent<ClippedPlaneSurface>();
            clipped.InjectAllClippedPlaneSurface(plane, new IBoundsClipper[] { clipper });

            var pokeGo = new GameObject("Poke");
            pokeGo.transform.SetParent(transform, false);
            var poke = pokeGo.AddComponent<PokeInteractable>();
            poke.InjectAllPokeInteractable(clipped);

            var rayGo = new GameObject("Ray");
            rayGo.transform.SetParent(transform, false);
            var ray = rayGo.AddComponent<RayInteractable>();
            ray.InjectAllRayInteractable(clipped);
        }

        void OnEnable()
        {
            if (_poke == null) _poke = GetComponentInChildren<PokeInteractable>(true);
            if (_ray == null) _ray = GetComponentInChildren<RayInteractable>(true);
            if (_poke != null) _poke.WhenStateChanged += OnStateChanged;
            if (_ray != null) _ray.WhenStateChanged += OnStateChanged;
            if (visual != null && !_restCaptured) { _visualRest = visual.localPosition; _restCaptured = true; }
            if (hoverHighlight != null) hoverHighlight.SetActive(false);
        }

        void OnDisable()
        {
            if (_poke != null) _poke.WhenStateChanged -= OnStateChanged;
            if (_ray != null) _ray.WhenStateChanged -= OnStateChanged;
            Hovered = false;
            _selected = false;
        }

        void OnStateChanged(InteractableStateChangeArgs args)
        {
            var p = _poke != null ? _poke.State : InteractableState.Normal;
            var r = _ray != null ? _ray.State : InteractableState.Normal;
            _selected = p == InteractableState.Select || r == InteractableState.Select;
            Hovered = _selected || p == InteractableState.Hover || r == InteractableState.Hover;
            if (hoverHighlight != null && hoverHighlight.activeSelf != Hovered) hoverHighlight.SetActive(Hovered);
            if (args.NewState == InteractableState.Select && args.PreviousState != InteractableState.Select) Press();
        }

        /// <summary>Press the button from code: the same path a poke or ray select takes.</summary>
        public void Press()
        {
            if (Time.unscaledTime - _lastPress < cooldownSeconds) return;
            _lastPress = Time.unscaledTime;
            _pressPulse = 1f;
            if (Pressed != null) Pressed(this);
        }

        void Update()
        {
            if (visual == null) return;
            if (_pressPulse > 0f) _pressPulse = Mathf.Max(0f, _pressPulse - Time.unscaledDeltaTime * 4f);
            float depth = (_selected ? 1f : _pressPulse) * pressDepth;
            var target = _visualRest + new Vector3(0f, 0f, depth);
            if ((visual.localPosition - target).sqrMagnitude > 1e-8f)
                visual.localPosition = Vector3.Lerp(visual.localPosition, target, Mathf.Min(1f, Time.unscaledDeltaTime * 20f));
        }
    }
}
