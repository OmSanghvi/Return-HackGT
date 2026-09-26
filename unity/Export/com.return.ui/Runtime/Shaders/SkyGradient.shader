// Inside-out sky dome: two-stop gradient (SkyTop to SkyBottom tokens) with procedural stars. Unlit URP.
Shader "Return/SkyGradient"
{
    Properties
    {
        _Top ("Top", Color) = (0.04, 0.06, 0.16, 1)
        _Bottom ("Horizon", Color) = (0.2, 0.22, 0.4, 1)
        _Stars ("Stars", Range(0, 1)) = 1
    }
    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Background" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }
            ZWrite Off
            Cull Front
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            CBUFFER_START(UnityPerMaterial)
                float4 _Top, _Bottom; float _Stars;
            CBUFFER_END
            struct A { float4 pos : POSITION; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float3 dir : TEXCOORD0; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i) { V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o); o.pos = TransformObjectToHClip(i.pos.xyz); o.dir = normalize(i.pos.xyz); return o; }
            float hash3(float3 p) { p = frac(p * 0.3183099 + 0.1); p *= 17.0; return frac(p.x * p.y * p.z * (p.x + p.y + p.z)); }
            half4 frag(V i) : SV_Target
            {
                float3 d = normalize(i.dir);
                float t = smoothstep(-0.05, 0.85, d.y);
                float3 col = lerp(_Bottom.rgb, _Top.rgb, t);
                // stars: sparse hashed cells on a coarse direction grid, fading toward the horizon
                float3 cell = floor(d * 90.0);
                float h = hash3(cell);
                float3 f = frac(d * 90.0) - 0.5;
                float star = step(0.9965, h) * smoothstep(0.16, 0.0, length(f)) * smoothstep(0.08, 0.5, d.y);
                float tw = 0.65 + 0.35 * sin(_Time.y * (1.5 + h * 6.0) + h * 40.0);
                col += star * tw * _Stars;
                return half4(col, 1);
            }
            ENDHLSL
        }
    }
}
