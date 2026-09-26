// Painted sky window with depth-map parallax, mist and optional arch mask.
// Port of web-app/src/world/shader.ts. Unlit, URP, cheap enough for Quest (3 depth taps per layer, 2 layers max).
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
        _Size ("Size (w,h)", Vector) = (16, 9, 0, 0)
        _Mix ("Crossfade", Range(0, 1)) = 0
        _Mist ("Mist", Range(0, 1)) = 0
        _Zoom ("Zoom", Float) = 0
        _Pointer ("Pointer (-0.5..0.5)", Vector) = (0, 0, 0, 0)
        _Fog ("Fog color", Color) = (0.93, 0.92, 0.9, 1)
        _Arch ("Arch (0 rect, 1 arch)", Float) = 0
        _Radius ("Corner radius (0..0.5 of min side)", Float) = 0
        _Alpha ("Alpha", Range(0, 1)) = 1
        _Light ("Light glow", Float) = 0
        _Edge ("Edge feather (uv fraction, 0 = hard)", Float) = 0
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

            CBUFFER_START(UnityPerMaterial)
                float4 _Size, _Pointer, _Fog;
                float _AspA, _AspB, _Mix, _Mist, _Zoom, _Arch, _Radius, _Alpha, _Light, _Edge;
            CBUFFER_END

            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };

            V vert(A i) { V o; o.pos = TransformObjectToHClip(i.pos.xyz); o.uv = i.uv; return o; }

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
                float px = max(fwidth(sd), 1e-5);
                float inside = 1.0 - smoothstep(-px, px, sd);
                if (inside <= 0.0) discard;

                float trans = sin(3.14159 * _Mix);
                float mist = saturate(_Mist + trans * 0.85);
                float blur = mist * 5.0;
                float3 a = paint(TEXTURE2D_ARGS(_MainTex, sampler_MainTex), TEXTURE2D_ARGS(_DepthTex, sampler_DepthTex), _AspA, luv, size, _Zoom + _Mix * 0.7, blur);
                float3 col = a;
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
                float feather = 1.0;
                if (_Edge > 0.0001) feather = smoothstep(0.0, _Edge, luv.x) * smoothstep(0.0, _Edge, 1.0 - luv.x) * smoothstep(0.0, _Edge * 1.4, 1.0 - luv.y);
                return half4(col, inside * _Alpha * feather);
            }
            ENDHLSL
        }
    }
}
