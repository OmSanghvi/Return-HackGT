using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// ~60 warm glowing points wandering the portal ring on curl-ish Perlin noise, soft-blinking, repelled by
    /// controllers within ~0.6m (see HubPointers) and drifting back after. A single ParticleSystem driven by
    /// script (GetParticles/SetParticles each frame); additive soft-dot material.
    /// </summary>
    public class Fireflies : MonoBehaviour
    {
        const int Count = 60;
        const float RepelRadius = 0.6f, RepelForce = 1.2f, WanderSpeed = 0.15f;

        ParticleSystem _ps;
        ParticleSystem.Particle[] _buf;
        Vector3[] _home, _pos;

        public static Fireflies Create(Transform parent)
        {
            var go = new GameObject("Fireflies"); go.transform.SetParent(parent, false);
            var ps = go.AddComponent<ParticleSystem>();
            var main = ps.main;
            main.loop = true; main.playOnAwake = false; main.maxParticles = Count;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.startLifetime = Mathf.Infinity; main.startSpeed = 0f; main.startSize = 0.035f;
            main.startColor = new Color(1f, 0.78f, 0.42f, 0.9f);
            var emission = ps.emission; emission.enabled = false;
            var shape = ps.shape; shape.enabled = false;

            var r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Billboard;
            r.sharedMaterial = Shapes.ParticleMaterial(additive: true);

            var f = go.AddComponent<Fireflies>();
            f._ps = ps;
            f._buf = new ParticleSystem.Particle[Count];
            f._home = new Vector3[Count]; f._pos = new Vector3[Count];
            for (int i = 0; i < Count; i++)
            {
                float ang = Random.value * Mathf.PI * 2f, rad = Random.Range(1f, 6f);
                var p = new Vector3(Mathf.Sin(ang) * rad, Random.Range(0.3f, 2.5f), Mathf.Cos(ang) * rad);
                f._home[i] = p; f._pos[i] = p;
                f._buf[i] = new ParticleSystem.Particle { position = p, startSize = main.startSize.constant, startColor = main.startColor.color, remainingLifetime = float.MaxValue, startLifetime = float.MaxValue };
            }
            ps.SetParticles(f._buf, Count);
            ps.Play();
            return f;
        }

        void Update()
        {
            var pts = HubPointers.Points;
            var t = Time.time;
            for (int i = 0; i < Count; i++)
            {
                // curl-ish wander: two offset Perlin lookups per axis so it never repeats in a visible cycle
                float nx = Mathf.PerlinNoise(_home[i].x * 0.6f + t * WanderSpeed, i * 0.37f) - 0.5f;
                float nz = Mathf.PerlinNoise(i * 0.51f, _home[i].z * 0.6f + t * WanderSpeed) - 0.5f;
                float ny = Mathf.PerlinNoise(_home[i].x * 0.4f, _home[i].z * 0.4f + t * WanderSpeed * 0.7f) - 0.5f;
                var target = _home[i] + new Vector3(nx, ny * 0.6f, nz) * 1.4f;
                target.y = Mathf.Clamp(target.y, 0.3f, 2.5f);

                var pos = Vector3.Lerp(_pos[i], target, Time.deltaTime * 0.5f);
                foreach (var p in pts)
                {
                    var d = pos - p.tip;
                    float dist = d.magnitude;
                    if (dist < RepelRadius && dist > 0.001f) pos += d / dist * (RepelRadius - dist) * RepelForce * Time.deltaTime;
                }
                _pos[i] = pos;

                float blink = 0.55f + 0.45f * Mathf.Sin(t * (1.1f + (i % 7) * 0.13f) + i * 1.7f);
                _buf[i].position = pos;
                var c = _buf[i].startColor; c.a = (byte)(blink * 0.9f * 255f); _buf[i].startColor = c;
            }
            _ps.SetParticles(_buf, Count);
        }
    }
}
