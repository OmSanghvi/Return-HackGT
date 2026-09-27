using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Keeps a world from ever cutting to black void at its edge: exponential fog tinted to the room's horizon color,
    /// density set from the world's bounds, a ground disc beyond those bounds that stays opaque out to a ring of
    /// distant hills (so there's no visible drop-off past the world's own floor), and the hills ring itself, far
    /// enough out that fog hides its own outer edge. Restores whatever RenderSettings.fog* was before this world
    /// loaded when it unloads.
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
            // hills start right where the ground disc ends, so there's no gap that shows a drop-off between them
            float hillsInner = worldRadius * 1.3f, hillsOuter = worldRadius * 3f + 10f;
            float discRadius = hillsInner;
            var disc = new GameObject("Ground");
            disc.transform.SetParent(transform, false);
            disc.transform.position = new Vector3(bounds.center.x, bounds.min.y - 0.05f, bounds.center.z); // just under the scene's own ground, so it only shows past the ground's edge
            disc.transform.rotation = Quaternion.Euler(90f, 0f, 0f);
            disc.transform.localScale = new Vector3(discRadius * 2f, discRadius * 2f, 1f);
            disc.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            var mr = disc.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            mr.receiveShadows = false;

            _material = WorldShaders.Create(WorldShaders.WorldEdge, "WorldEdge");
            var ground = Color.Lerp(horizon, Color.black, 0.2f); ground.a = 1f; // a touch darker than the horizon so it still reads as ground
            var edgeColor = ground; edgeColor.a = 1f; // opaque all the way out now: the hills ring (not a fade to transparent) is what hides the disc's own edge
            if (_material.HasProperty("_GroundColor")) _material.SetColor("_GroundColor", ground);
            if (_material.HasProperty("_EdgeColor")) _material.SetColor("_EdgeColor", edgeColor);
            if (_material.HasProperty("_InnerRadius")) _material.SetFloat("_InnerRadius", 0.9f); // nearly solid; no transparency left to hide a seam against the hills
            mr.sharedMaterial = _material;

            var hillColor = Color.Lerp(ground, new Color(0.4f, 0.55f, 0.35f), 0.3f); // ground tone nudged green, so the ring reads as land, not just a darker fog wall
            float maxHeight = Mathf.Clamp(worldRadius * 0.35f, 2f, 12f);
            var hills = HillsRing.Build(transform, hillsInner, hillsOuter, maxHeight, hillColor, Mathf.RoundToInt(worldRadius * 97f) + 13);
            hills.transform.position = disc.transform.position; // same height/center as the ground disc it continues
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
