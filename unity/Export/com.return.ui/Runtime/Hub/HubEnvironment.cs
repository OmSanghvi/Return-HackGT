using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The hub's sky: a real equirectangular skybox (RenderSettings.skybox) graded to match the room's mood, ambient
    /// light and fog tinted from its horizon color, and still water underfoot. Used for the hub and, with a different
    /// sky, for stub worlds (extras off there: no water/fireflies/motes/lanterns, just the plain fogged floor, so stub
    /// worlds stay cheap). Used to build a painted
    /// dome + panorama backdrop; that's gone in favor of Skyboxes, so the portal windows (RoomPortal) are now the
    /// only place a painted sky still gets drawn.
    /// </summary>
    public class HubEnvironment : MonoBehaviour
    {
        static readonly int Color_ = Shader.PropertyToID("_Color"), GlassBlurTex = Shader.PropertyToID("_ReturnGlassBlur");

        bool _extras, _dusk;
        SceneKey _scene;
        Material _sky, _floor;

        /// <summary>Which painted sky the hub opens on by default for a theme: the spring meadow and lake in day, the
        /// painted dusk hub sky after dark. Callers that pick the theme (HubController) should use this instead of
        /// hardcoding a SceneKey, so the sky always matches the theme.</summary>
        public static SceneKey DefaultScene(bool dusk) => dusk ? SceneKey.Hub : SceneKey.Meadow;

        /// <summary>Build under parent. arcDegrees is unused now that the sky is a real skybox rather than a curved panorama
        /// (kept so existing callers don't need to change). extras adds the still-water floor,
        /// fireflies, motes, lanterns and daytime birds, and toggles the hub ambience loop with this object's enabled
        /// state; leave false for stub worlds.</summary>
        public static HubEnvironment Build(Transform parent, Transform head, SceneKey scene, bool dusk, float arcDegrees = 150f, bool extras = false)
        {
            var go = new GameObject("Environment"); go.transform.SetParent(parent, false);
            var env = go.AddComponent<HubEnvironment>(); env._extras = extras; env._dusk = dusk; env._scene = scene;

            env._sky = Skyboxes.MaterialFor(scene);
            env.ApplyRenderSettings();

            if (extras)
            {
                // still water instead of the fogged disc: reflects the sky (no ripples, see WaterFloor)
                WaterFloor.Create(go.transform);
                Motes.Create(go.transform);
                // fireflies and lanterns only make sense once it's dark; day gets drifting blossom petals and birdsong instead
                if (dusk) { Fireflies.Create(go.transform); Lanterns.Create(go.transform); }
                else { Petals.Create(go.transform); BirdChirps.Create(go.transform); }
            }
            else
            {
                // fogged floor: a soft disc under the viewer, tinted to the sky's own horizon color
                var floor = new GameObject("Floor"); floor.transform.SetParent(go.transform, false);
                floor.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
                floor.transform.localRotation = Quaternion.Euler(90, 0, 0); floor.transform.localPosition = new Vector3(0, -0.02f, 0); floor.transform.localScale = new Vector3(26, 26, 1);
                env._floor = ReturnShaders.Create(ReturnShaders.Flat);
                var fc = Skyboxes.Horizon(scene); fc.a = 0.35f;
                env._floor.SetColor(Color_, fc); env._floor.SetFloat("_Radial", 1);
                floor.AddComponent<MeshRenderer>().sharedMaterial = env._floor;
            }
            return env;
        }

        /// <summary>RenderSettings.skybox/ambient/fog and the liquid-glass blur source, all from this environment's sky.
        /// Called once at Build and again on every OnEnable so returning to the hub after a world (which points these
        /// globals at its own sky) restores the hub's.</summary>
        void ApplyRenderSettings()
        {
            RenderSettings.skybox = _sky;
            var tex = Skyboxes.For(_scene);
            if (tex != null) Shader.SetGlobalTexture(GlassBlurTex, tex); // liquid-glass panels fake a backdrop blur by sampling this sky at a heavy mip
            var horizon = Skyboxes.Horizon(_scene);
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = horizon;
            RenderSettings.ambientEquatorColor = Color.Lerp(horizon, Color.white, 0.15f);
            RenderSettings.ambientGroundColor = Color.Lerp(horizon, Color.black, 0.35f);
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Exponential;
            RenderSettings.fogColor = horizon;
            RenderSettings.fogDensity = 0.01f; // gentle; WorldEdge sets its own bounds-aware density once a real world loads
        }

        // hub ambience follows this object's active state, which HubController drives by toggling the hub root (HubVisible):
        // on for the real hub (extras true), left alone for stub worlds so their HubEnvironment doesn't fight the hub's own.
        void OnEnable() { if (_sky != null) ApplyRenderSettings(); if (_extras) ReturnAudio.Ambience(true, 2f, _dusk); }
        void OnDisable() { if (_extras) ReturnAudio.Ambience(false, 1.2f, _dusk); }

        // _sky is a cached, shared Skyboxes material (reused across every HubEnvironment for the same scene), so it is
        // never destroyed here; only the floor material this instance owns (the meadow disc, or the stub-world fogged disc).
        void OnDestroy() { if (_floor != null) Destroy(_floor); }
    }
}
