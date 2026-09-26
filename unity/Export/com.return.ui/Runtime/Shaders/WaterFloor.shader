// Still water: dark unlit disc that fakes a sky reflection (no reflection camera, no grab pass), fresnel toward the
// horizon, star glints and slow sin-wave normal wobble, plus up to 8 expanding ripple rings. Unlit URP, cheap for Quest.
Shader "Return/WaterFloor"
{
    Properties
    {
        _Color ("Deep water", Color) = (0.02, 0.03, 0.08, 0.9)
        _Top ("Sky top (reflection)", Color) = (0.1, 0.13, 0.31, 1)
        _Bottom ("Sky horizon (reflection)", Color) = (0.29, 0.23, 0.43, 1)
        _Radial ("Disc falloff (0 flat, 1 radial)", Float) = 1
        [Enum(UnityEngine.Rendering.CompareFunction)] _ZTest ("ZTest", Float) = 4
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent+90" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            ZTest [_ZTest]
            Cull Off
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _Color, _Top, _Bottom;
                float _Radial;
            CBUFFER_END
            // Outside UnityPerMaterial on purpose: the SRP Batcher only uploads declared material properties, and an array can't
            // be one, so inside the cbuffer SetVectorArray was ignored on device and the rings never appeared. This makes the
            // shader SRP-Batcher-incompatible, which is fine for the one water disc. xy = world xz the ripple started at, w = start time.
            float4 _Ripples[8];

            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 worldPos : TEXCOORD1; UNITY_VERTEX_OUTPUT_STEREO };

            V vert(A i)
            {
                V o = (V)0;
                UNITY_SETUP_INSTANCE_ID(i);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.uv = i.uv;
                o.worldPos = TransformObjectToWorld(i.pos.xyz);
                return o;
            }

            float hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }

            half4 frag(V i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float3 viewDir = normalize(GetCameraPositionWS() - i.worldPos);

                // two slow procedural sin waves nudge the "reflection" sample, reading as a gentle ripple of the surface
                float t = _Time.y;
                float2 wobble = float2(sin(i.worldPos.x * 0.6 + t * 0.35), sin(i.worldPos.z * 0.5 - t * 0.28)) * 0.05;

                // fake reflection: reflect the view ray up into the sky gradient instead of sampling a reflection probe
                float3 refl = normalize(float3(viewDir.x, -viewDir.y, viewDir.z) + float3(wobble.x, 0, wobble.y));
                float skyT = smoothstep(-0.05, 0.6, refl.y);
                float3 skyCol = lerp(_Bottom.rgb, _Top.rgb, skyT);

                // fresnel: near-flat water reads dark, grazing angles (toward the horizon) pick up the sky
                float fres = pow(1.0 - saturate(viewDir.y), 3.0);
                float3 col = lerp(_Color.rgb, skyCol, saturate(fres * 0.85 + 0.1));

                // faint star glints, same hashed-cell trick as the dome, only where the water reads dark
                float3 cell = floor(float3(i.worldPos.xz * 6.0, 0));
                float h = hash(cell.xy);
                float2 f = frac(i.worldPos.xz * 6.0) - 0.5;
                float glint = step(0.985, h) * smoothstep(0.22, 0.0, length(f)) * (0.5 + 0.5 * sin(t * (2.0 + h * 4.0) + h * 30.0));
                col += glint * (1.0 - fres) * 0.5;

                // ripple rings: 8 slots, each expands ~2m over 2.5s and fades out
                float ring = 0;
                UNITY_UNROLL
                for (int r = 0; r < 8; r++)
                {
                    float2 origin = _Ripples[r].xy;
                    float age = t - _Ripples[r].w;
                    if (age < 0 || age > 2.5) continue;
                    float dist = length(i.worldPos.xz - origin);
                    float radius = age * 1.4;
                    float band = 1.0 - saturate(abs(dist - radius) / 0.12);
                    ring += band * band * (1.0 - age / 2.5);
                }
                col += ring * 0.35;

                float alpha = _Color.a;
                if (_Radial > 0.5) alpha *= smoothstep(1.0, 0.0, length(i.uv - 0.5) * 2.0);
                return half4(col, alpha);
            }
            ENDHLSL
        }
    }
}
