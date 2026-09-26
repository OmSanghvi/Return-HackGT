using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>~120 slow falling dust/petal motes, warm and cool tinted by the dusk palette, swaying, respawning at the top. Built-in ParticleSystem modules only, no per-frame script.</summary>
    public static class Motes
    {
        public static ParticleSystem Create(Transform parent)
        {
            var go = new GameObject("Motes"); go.transform.SetParent(parent, false);
            var ps = go.AddComponent<ParticleSystem>();
            var main = ps.main;
            main.loop = true; main.playOnAwake = true; main.maxParticles = 130;
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            main.startLifetime = 14f; main.startSpeed = 0.12f; main.startSize = 0.02f;
            main.startColor = new ParticleSystem.MinMaxGradient(new Color(1f, 0.85f, 0.6f, 0.55f), new Color(0.65f, 0.78f, 0.95f, 0.45f));
            main.gravityModifier = 0.01f;

            var emission = ps.emission; emission.rateOverTime = 9f; // ~120 alive at once given the 14s lifetime

            var shape = ps.shape;
            shape.shapeType = ParticleSystemShapeType.Circle; shape.radius = 7f; shape.position = new Vector3(0, 3.2f, 0); shape.rotation = new Vector3(90, 0, 0);

            var vel = ps.velocityOverLifetime; vel.enabled = true;
            vel.x = new ParticleSystem.MinMaxCurve(-0.05f, 0.05f); vel.z = new ParticleSystem.MinMaxCurve(-0.05f, 0.05f);

            var noise = ps.noise; noise.enabled = true; noise.strength = 0.15f; noise.frequency = 0.2f; noise.scrollSpeed = 0.1f;

            var col = ps.colorOverLifetime;
            col.enabled = true;
            var grad = new Gradient();
            grad.SetKeys(
                new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.15f), new GradientAlphaKey(1f, 0.8f), new GradientAlphaKey(0f, 1f) });
            col.color = grad;

            var r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Billboard;
            var shader = Shader.Find("Universal Render Pipeline/Particles/Unlit") ?? Shader.Find("Return/Flat");
            var mat = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
            if (mat.HasProperty("_BaseMap")) mat.SetTexture("_BaseMap", Shapes.Radial.texture);
            if (mat.HasProperty("_Surface")) mat.SetFloat("_Surface", 1f);
            if (mat.HasProperty("_Blend")) mat.SetFloat("_Blend", 0f); // alpha blend, not additive: motes should read as solid flecks, not glow
            if (mat.HasProperty("_ZWrite")) mat.SetFloat("_ZWrite", 0f);
            r.sharedMaterial = mat;

            ps.Play();
            return ps;
        }
    }
}
