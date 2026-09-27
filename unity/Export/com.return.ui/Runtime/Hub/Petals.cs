using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>~160 cherry-blossom petals drifting down over the day hub: pink gradient (no pure white), oval-shaped,
    /// slow fall with a gentle sway. Day's replacement for Fireflies and Lanterns (dusk-only, see HubEnvironment).
    /// Same technique as Motes: built-in ParticleSystem modules only, no per-frame script, so it stays cheap on Quest.</summary>
    public static class Petals
    {
        public static ParticleSystem Create(Transform parent)
        {
            var go = new GameObject("Petals"); go.transform.SetParent(parent, false);
            var ps = go.AddComponent<ParticleSystem>();
            var main = ps.main;
            main.loop = true; main.playOnAwake = true; main.maxParticles = 160;
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            main.startLifetime = 16f; main.startSpeed = 0.16f;
            main.startSize3D = true; // an oval petal, not a round fleck
            main.startSizeX = new ParticleSystem.MinMaxCurve(0.06f, 0.11f);
            main.startSizeY = new ParticleSystem.MinMaxCurve(0.036f, 0.066f); // ~0.6x width
            main.startSizeZ = new ParticleSystem.MinMaxCurve(0.06f, 0.11f); // all three axes must share a curve mode
            main.startColor = new ParticleSystem.MinMaxGradient(new Color(1f, 0.72f, 0.82f, 0.95f), new Color(0.98f, 0.83f, 0.9f, 0.9f));
            main.gravityModifier = 0.03f; // heavier and slower than Motes' dust
            main.startRotation = new ParticleSystem.MinMaxCurve(0f, 360f * Mathf.Deg2Rad);

            var emission = ps.emission; emission.rateOverTime = 10f;

            var shape = ps.shape;
            shape.shapeType = ParticleSystemShapeType.Circle; shape.radius = 10f; shape.position = new Vector3(0, 4.5f, 0); shape.rotation = new Vector3(90, 0, 0);

            var vel = ps.velocityOverLifetime; vel.enabled = true;
            vel.x = new ParticleSystem.MinMaxCurve(-0.06f, 0.06f); vel.z = new ParticleSystem.MinMaxCurve(-0.06f, 0.06f); vel.y = new ParticleSystem.MinMaxCurve(0f, 0f); // all three axes must share a curve mode

            var noise = ps.noise; noise.enabled = true; noise.strength = 0.25f; noise.frequency = 0.15f; noise.scrollSpeed = 0.08f; // the sway

            var rot = ps.rotationOverLifetime; rot.enabled = true; rot.z = new ParticleSystem.MinMaxCurve(-40f * Mathf.Deg2Rad, 40f * Mathf.Deg2Rad);

            var col = ps.colorOverLifetime;
            col.enabled = true;
            var grad = new Gradient();
            grad.SetKeys(
                new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.12f), new GradientAlphaKey(1f, 0.85f), new GradientAlphaKey(0f, 1f) });
            col.color = grad;

            var r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Billboard;
            r.sharedMaterial = Shapes.ParticleMaterial(additive: false); // solid soft flecks, like Motes, not glowing

            ps.Play();
            return ps;
        }
    }
}
