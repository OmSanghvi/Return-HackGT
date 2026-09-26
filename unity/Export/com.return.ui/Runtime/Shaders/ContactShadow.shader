// Soft blob shadow under a prop: a shared fan mesh (Runtime/Worlds/ContactShadow.cs) bakes the falloff into vertex alpha
// (opaque-ish at the center, transparent at the rim), so this shader is just an unlit alpha-blended vertex-color quad.
// Dark, transparent, no ZWrite: a decal sitting just above the ground, not geometry that should occlude anything.
Shader "Return/ContactShadow"
{
    Properties
    {
        _Color ("Shadow color", Color) = (0, 0, 0, 0.5)
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
            ZTest LEqual
            Cull Off
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            CBUFFER_START(UnityPerMaterial)
                float4 _Color;
            CBUFFER_END
            struct A { float4 pos : POSITION; float4 color : COLOR; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float4 color : COLOR; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i)
            {
                V o = (V)0;
                UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.color = i.color;
                return o;
            }
            half4 frag(V i) : SV_Target { return half4(_Color.rgb, _Color.a * i.color.a); }
            ENDHLSL
        }
    }
}
