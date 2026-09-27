// Painted sky window with depth-map parallax, mist and optional arch mask; or, with _Window on, a real 3D doorway
// that samples an equirect skybox by view direction so it reads as an opening onto that world's sky rather than
// a flat picture. Port of web-app/src/world/shader.ts. Unlit, URP, cheap enough for Quest.
Shader "Return/SkyParallax"
{
    Properties
    {
        _MainTex ("Sky A", 2D) = "white" {}
        _DepthTex ("Depth A", 2D) = "gray" {}
        _TexB ("Sky B", 2D) = "white" {}
        _DepthB ("Depth B", 2D) = "gray" {}
        _AspA ("Aspect A", Float) = 1.777
        _AspB ("Aspect B", Float) = 1.777
        _Size ("Size (w,h) in meters", Vector) = (16, 9, 0, 0)
        _Mix ("Crossfade", Range(0, 1)) = 0
        _Mist ("Mist", Range(0, 1)) = 0
        _Zoom ("Zoom", Float) = 0
        _Pointer ("Pointer (-0.5..0.5), painted mode only", Vector) = (0, 0, 0, 0)
        _Fog ("Fog color", Color) = (0.93, 0.92, 0.9, 1)
        _Arch ("Arch (0 rect, 1 arch)", Float) = 0
        _Radius ("Corner radius (0..0.5 of min side)", Float) = 0
        _Alpha ("Alpha", Range(0, 1)) = 1
        _Light ("Light glow (rim + hover)", Float) = 0
        _Edge ("Edge feather (uv fraction, 0 = hard)", Float) = 0
        _HorizonTint ("Edge tint (feathered rim melts toward this instead of just fading)", Color) = (0.9, 0.92, 0.95, 1)
        _TouchUV ("Touch point (uv)", Vector) = (-1, -1, 0, 0)
        _TouchTime ("Touch time (_Time.y at touch)", Float) = -100
        _Window ("Window mode (0 painted parallax, 1 real equirect doorway)", Float) = 0
        _SkyTex ("Sky (equirect, window mode)", 2D) = "grey" {}
        _HoverUV ("Hover point (uv, 0..1; unclamped, unlike _Pointer)", Vector) = (-1, -1, 0, 0)
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            TEXTURE2D(_DepthTex); SAMPLER(sampler_DepthTex);
            TEXTURE2D(_TexB); SAMPLER(sampler_TexB);
            TEXTURE2D(_DepthB); SAMPLER(sampler_DepthB);
            TEXTURE2D(_SkyTex); SAMPLER(sampler_SkyTex);

            CBUFFER_START(UnityPerMaterial)
                float4 _Size, _Pointer, _Fog, _TouchUV, _HorizonTint, _HoverUV;
                float _AspA, _AspB, _Mix, _Mist, _Zoom, _Arch, _Radius, _Alpha, _Light, _Edge, _TouchTime, _Window;
            CBUFFER_END

            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 worldPos : TEXCOORD1; UNITY_VERTEX_OUTPUT_STEREO };

            V vert(A i)
            {
                V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.uv = i.uv;
                o.worldPos = TransformObjectToWorld(i.pos.xyz); // window mode reads the sky by view direction from here
                return o;
            }

            float hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
            float noise(float2 p)
            {
                float2 i = floor(p), f = frac(p); f = f * f * (3.0 - 2.0 * f);
                return lerp(lerp(hash(i), hash(i + float2(1, 0)), f.x), lerp(hash(i + float2(0, 1)), hash(i + float2(1, 1)), f.x), f.y);
            }
            float fbm(float2 p) { float v = 0, a = 0.5; for (int i = 0; i < 3; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; } return v; }

            float sdBox(float2 p, float2 b, float r) { float2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
            float sdArch(float2 p, float2 b)
            {
                float r = b.x;
                return min(sdBox(p - float2(0.0, -r * 0.5), float2(b.x, b.y - r * 0.5), 0.0), length(p - float2(0.0, b.y - r)) - r);
            }

            float3 paint(TEXTURE2D_PARAM(tex, smp), TEXTURE2D_PARAM(dep, dsmp), float asp, float2 luv, float2 size, float zoom, float blur)
            {
                float cAsp = size.x / size.y;
                float2 s = cAsp > asp ? float2(1.0, asp / cAsp) : float2(cAsp / asp, 1.0);
                float ang = _Time.y * 6.2831 / 60.0;   // 60s drift (ReturnMotion.Drift)
                float2 uv = (luv - 0.5) * s * (0.9 - 0.012 * sin(ang)) + 0.5;
                uv += float2(sin(ang), cos(ang * 0.7)) * 0.006;
                float2 focus = float2(0.5, 0.45);
                float2 p = uv;
                for (int i = 0; i < 3; i++)   // refine: offset by the depth at the displaced point
                {
                    float d = SAMPLE_TEXTURE2D_LOD(dep, dsmp, p, 0).r;
                    float2 q = focus + (uv - focus) / (1.0 + zoom * (0.12 + 0.9 * d));
                    q -= _Pointer.xy * (d - 0.25) * 0.045;
                    q.x += (1.0 - smoothstep(0.0, 0.12, d)) * 0.012 * sin(_Time.y * 0.05);
                    p = q;
                }
                return SAMPLE_TEXTURE2D_LOD(tex, smp, clamp(p, 0.001, 0.999), blur).rgb;
            }

            half4 frag(V i) : SV_Target
            {
                float2 size = _Size.xy;
                float2 luv = i.uv;
                float2 c = (luv - 0.5) * size;
                float minSide = min(size.x, size.y);
                float sd = _Arch > 0.5 ? sdArch(c, size * 0.5) : sdBox(c, size * 0.5, _Radius * minSide);
                float aura = 0.0;
                if (_Window > 0.5)
                {
                    // frameless doorway: the opening is inset from the quad so a soft glow can bleed past it, and its
                    // edge wavers with slow noise, so it reads as a tear in the air rather than a cut-out picture
                    const float margin = 0.14;
                    float2 halfIn = size * 0.5 - margin;
                    float wisp = (fbm(c * 3.0 + float2(0.0, _Time.y * 0.35)) - 0.5) * 0.07;
                    sd = sdBox(c, halfIn, _Radius * minSide) + wisp;
                    aura = exp(-max(sd, 0.0) * 22.0) * saturate(-sdBox(c, size * 0.5, 0.0) / 0.03); // fades to 0 before the quad's own edge
                }
                float px = max(fwidth(sd), 1e-5);
                float inside = 1.0 - smoothstep(-px, px, sd);
                if (inside <= 0.0 && aura < 0.01) discard;

                float3 col;
                float mist = 0.0;
                if (_Window > 0.5)
                {
                    // real 3D doorway: sample the world's own equirect skybox by view direction, same convention as
                    // Return/SkyboxEquirect (u wraps atan2(x,z), v = 1 straight up), so the opening shifts with the
                    // viewer instead of reading as a flat picture.
                    float3 viewDir = normalize(i.worldPos - _WorldSpaceCameraPos);
                    // the doorway sits at eye height, so half of it looks below the horizon, where the graded skies are a
                    // flat white haze; mirror those rays back above it like still water so the whole opening shows sky
                    float below = step(viewDir.y, 0.0);
                    float3 d = normalize(float3(viewDir.x, abs(viewDir.y) * 0.8 + 0.03, viewDir.z));
                    float2 skyUV = float2(atan2(d.x, d.z) / (2.0 * PI) + 0.5, 1.0 - acos(clamp(d.y, -1.0, 1.0)) / PI);
                    col = SAMPLE_TEXTURE2D(_SkyTex, sampler_SkyTex, skyUV).rgb;
                    col = lerp(col, col * float3(0.82, 0.88, 0.95), below);                 // reflection reads a touch cooler and darker
                    col = saturate(lerp(dot(col, float3(0.299, 0.587, 0.114)).xxx, col, 1.25)); // a little more color than the hazy sky behind
                    // some rooms share the hub's own hazy daylight sky, so the opening has to read as somewhere else:
                    // deeper contrast, a touch darker, and shaded inward from the edge like a hole rather than a patch of sky
                    col = saturate((col - 0.5) * 1.3 + 0.42);
                    col *= lerp(0.6, 1.0, smoothstep(0.0, 0.28, -sd));
                }
                else
                {
                    float trans = sin(3.14159 * _Mix);
                    mist = saturate(_Mist + trans * 0.85);
                    float blur = mist * 5.0;
                    float3 a = paint(TEXTURE2D_ARGS(_MainTex, sampler_MainTex), TEXTURE2D_ARGS(_DepthTex, sampler_DepthTex), _AspA, luv, size, _Zoom + _Mix * 0.7, blur);
                    col = a;
                    if (_Mix > 0.001)
                    {
                        float3 b = paint(TEXTURE2D_ARGS(_TexB, sampler_TexB), TEXTURE2D_ARGS(_DepthB, sampler_DepthB), _AspB, luv, size, _Zoom + (1.0 - _Mix) * 0.4, blur);
                        col = lerp(a, b, smoothstep(0.3, 0.7, _Mix));
                    }
                    float n = fbm(luv * float2(2.2, 3.4) + float2(_Time.y * 0.018, _Time.y * 0.004));
                    col = lerp(col, dot(col, float3(0.299, 0.587, 0.114)).xxx, mist * 0.6);
                    float2 dl = luv - (_Pointer.xy + 0.5);
                    col += _Light * float3(1.0, 0.96, 0.88) * exp(-dot(dl, dl) * 7.0) * (1.0 - mist);
                    col = lerp(col, _Fog.rgb, 0.07 * n * (1.0 - mist));
                    col = lerp(col, _Fog.rgb, smoothstep(0.0, 1.0, mist * (0.75 + 0.5 * n)));
                }

                // touch ripple: a ring expanding out from the touch point over ~1s, then gone
                float age = _Time.y - _TouchTime;
                if (age >= 0.0 && age < 1.0)
                {
                    float d = length(luv - _TouchUV.xy);
                    float ring = exp(-age * 2.2) * exp(-abs(d - age * 0.7) * 12.0) * sin(d * 26.0 - age * 18.0);
                    col += ring * float3(1.0, 0.98, 0.9) * 0.4 * (1.0 - mist);
                }

                // luminous edge: a bright band right on the (wavering) edge that brightens on hover
                float rim = exp(-sd * sd * 2500.0);
                float3 glow = lerp(float3(1.0, 0.93, 0.85), float3(1.0, 0.8, 0.88), 0.35); // warm white with a blossom tint
                col += rim * (0.45 + 0.7 * _Light) * glow;

                // hover glow centered on the actual hit point (_HoverUV), not the corner-clamped _Pointer
                float2 dh = luv - _HoverUV.xy;
                col += _Light * exp(-dot(dh, dh) * 9.0) * float3(1.0, 0.95, 0.85);

                if (_Window > 0.5)
                {
                    // outside the opening: a dark shadow fading out with distance, so the edge still reads against a
                    // bright sky (a pale glow on its own melted into the daylight hub)
                    float a = max(inside, aura * (0.75 + 0.25 * _Light) * (1.0 - inside));
                    col = lerp(float3(0.05, 0.06, 0.09), col, inside);
                    return half4(col, a * _Alpha);
                }
                float feather = 1.0;
                if (_Edge > 0.0001) feather = smoothstep(0.0, _Edge, luv.x) * smoothstep(0.0, _Edge, 1.0 - luv.x) * smoothstep(0.0, _Edge * 1.4, 1.0 - luv.y);
                // as the rim feathers out, tint it toward the surrounding sky's horizon color first, so it melts into
                // the real skybox behind instead of just fading to nothing (a hard-edged cutout).
                col = lerp(_HorizonTint.rgb, col, feather);
                return half4(col, inside * _Alpha * feather);
            }
            ENDHLSL
        }
    }
}
