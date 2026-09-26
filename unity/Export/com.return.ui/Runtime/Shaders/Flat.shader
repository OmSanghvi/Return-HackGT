// Flat color, optionally with a radial alpha falloff. Used for the hub floor fog and the screen fade quad. Unlit URP.
Shader "Return/Flat"
{
    Properties
    {
        _Color ("Color", Color) = (1, 1, 1, 1)
        _Radial ("Radial falloff (0 flat, 1 radial)", Float) = 0
        [Enum(UnityEngine.Rendering.CompareFunction)] _ZTest ("ZTest", Float) = 4
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent+100" "RenderPipeline" = "UniversalPipeline" }
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
                float4 _Color; float _Radial;
            CBUFFER_END
            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i) { V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o); o.pos = TransformObjectToHClip(i.pos.xyz); o.uv = i.uv; return o; }
            half4 frag(V i) : SV_Target
            {
                float a = _Color.a;
                if (_Radial > 0.5) a *= smoothstep(1.0, 0.0, length(i.uv - 0.5) * 2.0);
                return half4(_Color.rgb, a);
            }
            ENDHLSL
        }
    }
}
