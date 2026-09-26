// Comfort vignette for locomotion: darkens the edge of view, camera-attached. Unlit URP, one uniform.
// The ring is measured in screen space, not quad UVs: the quad is 5m wide at 0.29m, so only its middle ~14% is ever in view.
Shader "Return/Vignette"
{
    Properties
    {
        _Amount ("Amount", Range(0, 1)) = 0
        [Enum(UnityEngine.Rendering.CompareFunction)] _ZTest ("ZTest", Float) = 4
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent+150" "RenderPipeline" = "UniversalPipeline" }
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
                float _Amount;
            CBUFFER_END
            struct A { float4 pos : POSITION; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i) { V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o); o.pos = TransformObjectToHClip(i.pos.xyz); return o; }
            half4 frag(V i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float d = length(GetNormalizedScreenSpaceUV(i.pos) - 0.5) * 2.0;
                float ring = smoothstep(0.45, 1.05, d);
                return half4(0, 0, 0, ring * _Amount);
            }
            ENDHLSL
        }
    }
}
