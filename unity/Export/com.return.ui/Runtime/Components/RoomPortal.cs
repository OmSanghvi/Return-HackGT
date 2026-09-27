using System;
using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The doorway into a room for the VR hub: a real equirect sky seen through a frameless opening whose glowing edge
    /// wavers and bleeds light into the air, with motes riding the edge and drifting out toward the viewer and a warm light pool on the floor in
    /// front of it. Grounded (no bob): callers place it so its bottom rests on the floor. Pinch or click it to step in.
    /// Rig-agnostic: an XR interactor calls Enter(), or a mouse/PhysicsRaycaster click on the collider does.
    /// </summary>
    [RequireComponent(typeof(BoxCollider))]
    public class RoomPortal : MonoBehaviour, UnityEngine.EventSystems.IPointerClickHandler, UnityEngine.EventSystems.IPointerEnterHandler, UnityEngine.EventSystems.IPointerMoveHandler
    {
        static readonly int SkyTex = Shader.PropertyToID("_SkyTex"), Window = Shader.PropertyToID("_Window"), Size = Shader.PropertyToID("_Size"),
            Arch = Shader.PropertyToID("_Arch"), Radius = Shader.PropertyToID("_Radius"), Fog = Shader.PropertyToID("_Fog"), Light = Shader.PropertyToID("_Light"),
            TouchUV = Shader.PropertyToID("_TouchUV"), TouchTime = Shader.PropertyToID("_TouchTime"), HoverUV = Shader.PropertyToID("_HoverUV"),
            HorizonTint = Shader.PropertyToID("_HorizonTint"), ColorProp = Shader.PropertyToID("_Color");

        public string roomId;
        /// <summary>Raised when the portal is pinched, poked, ray-clicked or mouse-clicked. The hub decides what that means for the room's state.</summary>
        public event Action<string> Activated;
        /// <summary>Raised for every new portal. XR glue subscribes to attach an interactable.</summary>
        public static event Action<RoomPortal> Created;
        /// <summary>Raised the first time any portal is hovered or touched. HubIntro uses this to dismiss the guided nudge for good.</summary>
        public static event Action AnyHoverOrTouch;
        public Collider Collider => GetComponent<Collider>();
        Material _m, _pool, _moteMat; Color _poolBase; float _hover; float _lastTouchSfx = -10f;
        Transform _head; AudioSource _hum; float _humBoost;

        const float BaseHumVolume = 0.05f;
        const float FacingBoost = 0.04f;    // small lift for the portal the head faces most directly
        const float DuckMultiplier = 0.15f; // hums nearly vanish while a room is being entered/occupied

        static bool _ducked;
        static int _facingFrame = -1;
        static RoomPortal _facingBest, _pendingFacingBest;
        static float _pendingFacingDot;

        /// <summary>Duck (or restore) every portal's hum at once. HubController calls this on EnteringRoom, and back on returning to the hub.</summary>
        public static void SetHumDucked(bool ducked) => _ducked = ducked;

        /// <summary>Maps a head (or pointer) position, already in the portal's local space, to the shader's -0.5..0.5 pointer range. Pure and testable.</summary>
        public static Vector2 HeadOffset(Vector3 localPosition, float leanScale) => new Vector2(
            Mathf.Clamp(-localPosition.x * leanScale, -0.5f, 0.5f),
            Mathf.Clamp(-localPosition.y * leanScale, -0.5f, 0.5f));

        /// <summary>1 when looking straight at the portal, 0 (or negative, clamped) facing away. Pure and testable.</summary>
        public static float FacingWeight(Vector3 headForward, Vector3 headToPortal) =>
            Mathf.Clamp01(Vector3.Dot(headForward.normalized, headToPortal.normalized));

        /// <summary>Yaw-only billboard: <paramref name="t"/> faces whoever is at <paramref name="head"/>, forward pointing
        /// away from them (the same convention SpatialPanel.PlaceInFront uses), so label text reads correctly from any side.</summary>
        public static void FaceYaw(Transform t, Transform head)
        {
            if (t == null || head == null) return;
            var fwd = t.position - head.position; fwd.y = 0;
            if (fwd.sqrMagnitude < 0.0001f) fwd = Vector3.forward;
            t.rotation = Quaternion.LookRotation(fwd.normalized);
        }

        public static RoomPortal Create(Transform parent, Room room, Vector3 localPosition)
        {
            var go = new GameObject("Portal:" + room.title);
            go.transform.SetParent(parent, false); go.transform.localPosition = localPosition;
            go.transform.localScale = new Vector3(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 1);
            var p = go.AddComponent<RoomPortal>(); p.roomId = room.id;
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var r = go.AddComponent<MeshRenderer>();
            p._m = ReturnShaders.Create(ReturnShaders.SkyParallax);
            p._m.SetTexture(SkyTex, Skyboxes.For(room.scene));
            p._m.SetFloat(Window, 1f); p._m.SetFloat(Arch, 0f); p._m.SetFloat(Radius, 0.2f);
            p._m.SetVector(Size, new Vector4(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 0, 0));
            var horizon = Skyboxes.Horizon(room.scene);
            p._m.SetFloat("_Edge", 0.06f); p._m.SetColor(HorizonTint, horizon); // feathered rim melts into the real sky behind instead of a hard cutout
            r.sharedMaterial = p._m;
            var col = go.GetComponent<BoxCollider>(); col.size = new Vector3(1, 1, 0.1f);
            p._hum = ReturnAudio.PortalHumSource(go.transform, room.scene, BaseHumVolume);
            p.BuildDressing(go.transform, horizon);
            Created?.Invoke(p);
            return p;
        }

        /// <summary>Doorway dressing (no frame: the shader draws a glowing, wavering edge instead): motes spilling out
        /// of the opening, motes riding along its edge, and a floor light pool, all under the portal's own
        /// (width/height-scaled) transform so they bloom and shrink with it like PortalTransition and HomePortal animate.</summary>
        void BuildDressing(Transform quad, Color horizon)
        {
            BuildOverflow(quad, horizon);
            BuildEdgeMotes(quad, horizon);
            BuildLightPool(quad, horizon, ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight);
        }

        /// <summary>Tiny bright motes born on the opening's outline that rise and drift a few cm, so the edge shimmers
        /// and reads as a volume in the air rather than a flat border.</summary>
        void BuildEdgeMotes(Transform quad, Color horizon)
        {
            var go = new GameObject("EdgeMotes"); go.transform.SetParent(quad, false);
            var ps = go.AddComponent<ParticleSystem>();
            var main = ps.main;
            main.loop = true; main.startLifetime = new ParticleSystem.MinMaxCurve(1.5f, 3f); main.startSpeed = 0f;
            main.startSize = new ParticleSystem.MinMaxCurve(0.015f, 0.04f);
            main.maxParticles = 90; main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.startColor = new ParticleSystem.MinMaxGradient(Color.Lerp(horizon, Color.white, 0.7f), new Color(1f, 0.82f, 0.9f));
            var emission = ps.emission; emission.rateOverTime = 40f;
            var shape = ps.shape; shape.shapeType = ParticleSystemShapeType.BoxEdge;
            shape.scale = new Vector3(1f - 0.28f / ReturnSpatial.PortalWidth, 1f - 0.28f / ReturnSpatial.PortalHeight, 0f); // on the shader's inset opening
            var vel = ps.velocityOverLifetime; vel.enabled = true; vel.space = ParticleSystemSimulationSpace.World;
            vel.x = new ParticleSystem.MinMaxCurve(-0.03f, 0.03f); vel.y = new ParticleSystem.MinMaxCurve(0.02f, 0.08f); vel.z = new ParticleSystem.MinMaxCurve(-0.03f, 0.03f);
            var col = ps.colorOverLifetime; col.enabled = true;
            var grad = new Gradient();
            grad.SetKeys(new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.2f), new GradientAlphaKey(0f, 1f) });
            col.color = grad;
            var r = go.GetComponent<ParticleSystemRenderer>(); r.sharedMaterial = _moteMat != null ? _moteMat : Shapes.ParticleMaterial(additive: true);
            ps.Play();
        }

        /// <summary>Soft glowing motes emitted from the doorway's opening, drifting slowly out along local -Z (the
        /// side the viewer stands on: HubController.LayoutRing points the portal's forward away from the ring
        /// center). Simulation space World so they spill out into the room instead of stretching with the quad.</summary>
        void BuildOverflow(Transform quad, Color horizon)
        {
            var go = new GameObject("Overflow"); go.transform.SetParent(quad, false);
            var ps = go.AddComponent<ParticleSystem>();
            var main = ps.main;
            main.loop = true; main.startLifetime = 4f; main.startSpeed = 0f;
            main.startSize = new ParticleSystem.MinMaxCurve(0.02f, 0.05f);
            main.maxParticles = 40; main.simulationSpace = ParticleSystemSimulationSpace.World;
            var moteColor = Color.Lerp(horizon, Color.white, 0.4f);
            main.startColor = moteColor;

            var emission = ps.emission; emission.rateOverTime = 7.5f; // ~30 alive at a 4s lifetime

            var shape = ps.shape; shape.shapeType = ParticleSystemShapeType.Box; shape.scale = new Vector3(0.85f, 0.85f, 0.02f);

            var vel = ps.velocityOverLifetime; vel.enabled = true;
            vel.space = ParticleSystemSimulationSpace.Local; vel.z = new ParticleSystem.MinMaxCurve(-0.12f);

            var colorLifetime = ps.colorOverLifetime; colorLifetime.enabled = true;
            var grad = new Gradient();
            grad.SetKeys(
                new[] { new GradientColorKey(moteColor, 0f), new GradientColorKey(moteColor, 1f) },
                new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(0.6f, 0.25f), new GradientAlphaKey(0.6f, 0.75f), new GradientAlphaKey(0f, 1f) });
            colorLifetime.color = grad;

            var psr = ps.GetComponent<ParticleSystemRenderer>();
            _moteMat = Shapes.ParticleMaterial(true);
            psr.material = _moteMat;
            psr.renderMode = ParticleSystemRenderMode.Billboard;
        }

        /// <summary>A warm glow pool lying flat on the floor just in front of the doorway (toward the viewer),
        /// brightening with hover, same shader/tint approach as the old halo it replaces.</summary>
        void BuildLightPool(Transform quad, Color horizon, float w, float h)
        {
            var go = new GameObject("LightPool"); go.transform.SetParent(quad, false);
            go.transform.localRotation = Quaternion.Euler(90, 0, 0);
            go.transform.localPosition = new Vector3(0, -0.5f + 0.02f / h, -0.55f);
            go.transform.localScale = new Vector3(2f / w, 1.3f, 1f);
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var r = go.AddComponent<MeshRenderer>(); r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; r.receiveShadows = false;
            _pool = ReturnShaders.Create(ReturnShaders.ParticleGlow);
            _poolBase = Color.Lerp(horizon, new Color(1f, 0.96f, 0.88f), 0.6f);
            _poolBase.a = ThemeManager.Current == ReturnTheme.Dusk ? 0.28f : 0.1f;
            _pool.SetColor(ColorProp, _poolBase);
            r.sharedMaterial = _pool;
        }

        void Update()
        {
            _hover = Mathf.Lerp(_hover, 0, 1f - Mathf.Exp(-4f * Time.deltaTime));
            _m.SetFloat(Light, _hover * 0.5f);
            var fog = ThemeManager.Current == ReturnTheme.Dusk ? new Color32(10, 15, 31, 255) : new Color32(237, 234, 228, 255);
            _m.SetColor(Fog, fog);
            if (_pool != null) _pool.SetColor(ColorProp, Color.Lerp(_poolBase, Color.Lerp(_poolBase, Color.white, 0.6f), _hover));
            UpdateHum();
        }

        /// <summary>Ducks with EnteringRoom, boosts a touch when the head faces this portal most directly, restores on return.</summary>
        void UpdateHum()
        {
            if (_head == null && Camera.main != null) _head = Camera.main.transform;
            if (_hum == null || _head == null) return;
            if (_facingFrame != Time.frameCount)
            {
                _facingFrame = Time.frameCount; _facingBest = _pendingFacingBest;
                _pendingFacingBest = null; _pendingFacingDot = -2f;
            }
            float dot = FacingWeight(_head.forward, transform.position - _head.position);
            if (dot > _pendingFacingDot) { _pendingFacingDot = dot; _pendingFacingBest = this; }

            _humBoost = Mathf.Lerp(_humBoost, _facingBest == this ? FacingBoost : 0f, 1f - Mathf.Exp(-2f * Time.deltaTime));
            float target = (BaseHumVolume + _humBoost) * (_ducked ? DuckMultiplier : 1f) * ReturnAudio.MasterVolume;
            _hum.volume = Mathf.Lerp(_hum.volume, target, 1f - Mathf.Exp(-3f * Time.deltaTime));
        }

        /// <summary>Call while a ray or hand hovers to brighten the window.</summary>
        public void Hover() { _hover = 1f; AnyHoverOrTouch?.Invoke(); }

        /// <summary>Call every frame with the actual hover hit point (ray or pointer) to brighten the window and
        /// center its hover glow there, unlike the old corner-clamped pointer parallax.</summary>
        public void HoverAt(Vector3 worldPoint)
        {
            _hover = 1f;
            var local = transform.InverseTransformPoint(worldPoint);
            _m.SetVector(HoverUV, new Vector4(local.x + 0.5f, local.y + 0.5f, 0, 0));
        }

        /// <summary>Call with a world-space hit point (ray, poke or pinch) to brighten the window and ripple the sky from that point.</summary>
        public void Touch(Vector3 worldPoint)
        {
            _hover = 1f;
            var local = transform.InverseTransformPoint(worldPoint);
            _m.SetVector(TouchUV, new Vector4(local.x + 0.5f, local.y + 0.5f, 0, 0));
            _m.SetFloat(TouchTime, Time.time);
            AnyHoverOrTouch?.Invoke();
            if (Time.time - _lastTouchSfx > 0.15f) { _lastTouchSfx = Time.time; ReturnAudio.PlayAt(ReturnAudio.UiHover, transform.position, 0.18f); }
        }

        public void Activate() { Activated?.Invoke(roomId); }
        public void OnPointerClick(UnityEngine.EventSystems.PointerEventData e) { Activate(); }
        public void OnPointerEnter(UnityEngine.EventSystems.PointerEventData e) { HoverAt(e.pointerCurrentRaycast.worldPosition); }
        public void OnPointerMove(UnityEngine.EventSystems.PointerEventData e) { HoverAt(e.pointerCurrentRaycast.worldPosition); }

        static readonly int MistId = Shader.PropertyToID("_Mist"), AlphaId = Shader.PropertyToID("_Alpha");
        /// <summary>How the window reads: mist 0 clear to 1 fogged, alpha 1 solid to 0 gone.</summary>
        public void SetPresentation(float mist, float alpha) { _m.SetFloat(MistId, mist); _m.SetFloat(AlphaId, alpha); }
        void OnDestroy()
        {
            if (_m != null) Destroy(_m);
            if (_pool != null) Destroy(_pool);
            if (_moteMat != null) Destroy(_moteMat);
        }
    }
}
