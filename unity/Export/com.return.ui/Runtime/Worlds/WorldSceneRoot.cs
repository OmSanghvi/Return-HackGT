using System.Collections.Generic;
using Return.Data;
using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The anchor of a room's world scene. Author (or let the agent author) everything as a child of this, in viewer space:
    /// +Z is the way the viewer faces on arrival, y = 0 is the floor, the viewer stands at the local origin.
    /// SceneWorldLoader moves this under the viewer when the scene loads, so a child at (0, 0, 1.5) appears 1.5 m ahead.
    /// </summary>
    public class WorldSceneRoot : MonoBehaviour
    {
        [Tooltip("Surround the world with the room's painted sky (the same dome + panorama the stub world uses). Turn off once the scene brings its own surroundings.")]
        public bool buildSky = true;
        [Tooltip("Looping ambient bed plus a reverb zone sized from the world.")]
        public bool buildAmbience = true;
        [Tooltip("Soft blob shadow under every prop resting on the ground.")]
        public bool buildContactShadows = true;
        [Tooltip("Dust motes, foliage sway and candle/lantern flicker.")]
        public bool buildLife = true;
        [Tooltip("Fog plus a ground disc that dissolves into the horizon, so the world never cuts to black void.")]
        public bool buildEdge = true;

        /// <summary>Place the world under the viewer (floor at y = 0, facing the head's yaw), build its sky, then the
        /// runtime polish passes that are generic over whatever props this world happens to have.</summary>
        public void Arrive(Room room, Transform head)
        {
            var at = head != null ? head.position : Vector3.zero;
            transform.SetPositionAndRotation(new Vector3(at.x, 0f, at.z), Quaternion.Euler(0f, head != null ? head.eulerAngles.y : 0f, 0f));
            if (buildSky && room != null) HubEnvironment.Build(transform, head, room.scene, UIAssets.IsDusk(room.scene), 200f);

            var bounds = PropBounds(transform);
            EnsureSun();
            if (buildEdge) WorldEdge.Build(transform, room, bounds);
            if (buildAmbience) WorldAmbience.Build(transform, room, bounds);
            if (buildContactShadows) ContactShadow.Build(transform, bounds);
            if (buildLife) WorldLife.Build(transform, bounds);
        }

        /// <summary>Renderers under this root that are world props, i.e. everything except the sky dome/panorama/floor
        /// HubEnvironment builds under its own "Environment" child.</summary>
        /// <summary>World scenes may ship without a light; props then read flat and WorldLife's dust has no direction. Adds one
        /// soft warm sun at the same angle Return > Bake World Lighting uses, only when the scene has no directional light.</summary>
        void EnsureSun()
        {
            foreach (var l in GetComponentsInChildren<Light>()) if (l.type == LightType.Directional) { if (RenderSettings.sun == null) RenderSettings.sun = l; return; }
            var go = new GameObject("Sun"); go.transform.SetParent(transform, false);
            go.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            var sun = go.AddComponent<Light>();
            sun.type = LightType.Directional; sun.color = new Color(1f, 0.96f, 0.9f); sun.intensity = 1.1f;
            sun.shadows = LightShadows.Soft; sun.shadowStrength = 0.6f;
            RenderSettings.sun = sun;
        }

        public static IEnumerable<Renderer> PropRenderers(Transform root)
        {
            foreach (Transform child in root)
            {
                if (child.name == "Environment") continue;
                foreach (var r in child.GetComponentsInChildren<Renderer>(true)) yield return r;
            }
        }

        /// <summary>Combined world-space bounds of the world's props, or a 10 m fallback box if it has none yet
        /// (an empty or not-yet-authored world, so the polish passes below still have something to size against).</summary>
        public static Bounds PropBounds(Transform root)
        {
            Bounds? b = null;
            foreach (var r in PropRenderers(root))
            {
                if (b.HasValue) { var v = b.Value; v.Encapsulate(r.bounds); b = v; }
                else b = r.bounds;
            }
            return b ?? new Bounds(root.position, Vector3.one * 10f);
        }
    }

    /// <summary>Loads a shader for a runtime-built mesh the same way ReturnShaders does (Shader.Find, falling back to a
    /// template material under Resources/ReturnUI/Shaders so a Quest build doesn't strip it), without editing that shared
    /// file. If Resources/ReturnUI/Shaders/{templateName}.mat is missing, this falls back to Return/Flat and logs once.</summary>
    public static class WorldShaders
    {
        public const string ContactShadow = "Return/ContactShadow";
        public const string WorldEdge = "Return/WorldEdge";
        public const string Photo = "Return/Photo";
        const string Root = "ReturnUI/Shaders/";

        public static Material Create(string shaderName, string templateName)
        {
            var s = Shader.Find(shaderName);
            if (s == null)
            {
                var template = Resources.Load<Material>(Root + templateName);
                s = template != null ? template.shader : null;
            }
            if (s == null)
            {
                Debug.LogError("[Return] Shader '" + shaderName + "' is not in the build; add a template material at Resources/" + Root + templateName + ".mat.");
                s = ReturnShaders.Get(ReturnShaders.Flat);
            }
            return new Material(s) { hideFlags = HideFlags.HideAndDontSave };
        }
    }
}
