using UnityEngine;

namespace Return.Design
{
    /// <summary>
    /// Shaders for the package's runtime-built meshes. Shader.Find only sees shaders that made it into the player build, and no
    /// scene or asset references Return/*, so in an Android/Quest build they were stripped and every new Material(null) threw,
    /// leaving the hub unbuilt (a black view). Each shader now has a template material in Resources/ReturnUI/Shaders that pulls
    /// it, and the variants it needs, into the build. Create materials here, never with Shader.Find directly.
    /// </summary>
    public static class ReturnShaders
    {
        public const string Flat = "Return/Flat", SkyGradient = "Return/SkyGradient", SkyParallax = "Return/SkyParallax",
            Vignette = "Return/Vignette", WaterFloor = "Return/WaterFloor", ParticlesUnlit = "Universal Render Pipeline/Particles/Unlit";
        const string Root = "ReturnUI/Shaders/";

        /// <summary>The named shader, or null if it isn't in the build.</summary>
        public static Shader Get(string name)
        {
            var s = Shader.Find(name);
            if (s != null) return s;
            var template = Resources.Load<Material>(Root + TemplateName(name));
            return template != null && template.shader != null ? template.shader : null;
        }

        /// <summary>New hidden material using the named shader. A missing shader logs and falls back to Return/Flat instead of
        /// throwing, so one stripped shader can't stop the whole hub from building.</summary>
        public static Material Create(string name)
        {
            var s = Get(name);
            if (s == null)
            {
                Debug.LogError($"[Return] Shader '{name}' is not in the build; add its template material under Resources/{Root}.");
                s = Get(Flat) ?? Shader.Find("Hidden/InternalErrorShader");
            }
            return new Material(s) { hideFlags = HideFlags.HideAndDontSave };
        }

        static string TemplateName(string name) => name == ParticlesUnlit ? "ParticlesUnlit" : name.Substring(name.LastIndexOf('/') + 1);
    }
}
