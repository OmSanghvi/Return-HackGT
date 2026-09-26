using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Keeps a world from ever cutting to black void at its edge: exponential fog tinted to the room's horizon color,
    /// density set from the world's bounds, plus a large ground disc beyond those bounds that dissolves from a ground
    /// color to fully transparent toward its rim, so the floor melts into the real skybox behind it instead of stopping short.
    /// Restores whatever RenderSettings.fog* was before this world loaded when it unloads.
    /// </summary>
    public class WorldEdge : MonoBehaviour
    {
        bool _prevFog; FogMode _prevMode; Color _prevColor; float _prevDensity;
        Material _material;

        public static WorldEdge Build(Transform root, Room room, Bounds bounds)
        {
            var go = new GameObject("Edge");
            go.transform.SetParent(root, false);
            var edge = go.AddComponent<WorldEdge>();
            edge.Setup(room, bounds);
            return edge;
        }

        void Setup(Room room, Bounds bounds)
        {
            _prevFog = RenderSettings.fog; _prevMode = RenderSettings.fogMode; _prevColor = RenderSettings.fogColor; _prevDensity = RenderSettings.fogDensity;

            // Sampled from the room's own skybox (Skyboxes.Horizon), so the fog and ground disc always match the real
            // sky behind them instead of a hand-picked token color.
            Color horizon = room != null ? Skyboxes.Horizon(room.scene) : Color.gray;

            float worldRadius = Mathf.Max(bounds.extents.x, bounds.extents.z, 3f);
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Exponential;
            RenderSettings.fogColor = horizon;
            RenderSettings.fogDensity = Mathf.Clamp(1.1f / worldRadius, 0.004f, 0.08f);

            BuildGroundDisc(bounds, worldRadius, horizon);
        }

        void BuildGroundDisc(Bounds bounds, float worldRadius, Color horizon)
        {
            float discRadius = worldRadius * 2.2f + 3f; // well beyond the world's own footprint
            var disc = new GameObject("Ground");
            disc.transform.SetParent(transform, false);
            disc.transform.position = new Vector3(bounds.center.x, bounds.min.y + 0.01f, bounds.center.z);
            disc.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            disc.transform.localScale = new Vector3(discRadius * 2f, discRadius * 2f, 1f);
            disc.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var mr = disc.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            mr.receiveShadows = false;

            _material = WorldShaders.Create(WorldShaders.WorldEdge, "WorldEdge");
            var ground = Color.Lerp(horizon, Color.black, 0.45f); ground.a = 1f; // darker than the horizon so the disc still reads as ground near the props
            var edgeColor = horizon; edgeColor.a = 0f;
            if (_material.HasProperty("_GroundColor")) _material.SetColor("_GroundColor", ground);
            if (_material.HasProperty("_EdgeColor")) _material.SetColor("_EdgeColor", edgeColor);
            if (_material.HasProperty("_InnerRadius")) _material.SetFloat("_InnerRadius", Mathf.Clamp01(worldRadius / discRadius));
            mr.sharedMaterial = _material;
        }

        void OnDestroy()
        {
            RenderSettings.fog = _prevFog;
            RenderSettings.fogMode = _prevMode;
            RenderSettings.fogColor = _prevColor;
            RenderSettings.fogDensity = _prevDensity;
            if (_material != null) Destroy(_material);
        }
    }
}
