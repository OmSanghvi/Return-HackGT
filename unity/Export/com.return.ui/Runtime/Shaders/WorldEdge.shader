// Ground disc beyond a world's props (Runtime/Worlds/WorldEdge.cs): lerps from a ground color at its center to the
// horizon color, fully transparent, at its rim. Port of the Flat shader's UV-distance radial falloff, plus a color lerp
// so the disc's edge visually matches the sky it fades into instead of just vanishing.
Shader "Return/WorldEdge"
{
    Properties
    {
        _GroundColor ("Ground color", Color) = (0.3, 0.3, 0.3, 1)
        _EdgeColor ("Edge/horizon color", Color) = (0.3, 0.3, 0.3, 0)
        _InnerRadius ("Inner radius (0..1 of the disc; solid ground before this)", Range(0, 0.95)) = 0.35
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent-1" "RenderPipeline" = "UniversalPipeline" }
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
            CBUFFER_START(UnityPerMaterial)
                float4 _GroundColor; float4 _EdgeColor; float _InnerRadius;
            CBUFFER_END
            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i)
            {
                V o = (V)0;
                UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.uv = i.uv;
                return o;
            }
            half4 frag(V i) : SV_Target
            {
                float d = saturate((length(i.uv - 0.5) * 2.0 - _InnerRadius) / max(1.0 - _InnerRadius, 0.001));
                return lerp(_GroundColor, _EdgeColor, d);
            }
            ENDHLSL
        }
    }
}
