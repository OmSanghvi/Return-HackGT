// Soft round glow for particle billboards (fireflies, motes). Bakes the transparent blend state straight into
// the shader instead of the surface-type keyword URP's Particles/Unlit shader uses, which gets stripped out of
// device builds when nothing in Resources enables the exact keyword combo a runtime material needs (see the
// comment on ReturnShaders): that left the quad drawing with the build's leftover opaque pass, a hard square.
// _DstBlend is a plain material property, not a keyword, so Shapes.ParticleMaterial can flip additive vs alpha
// blend at runtime with SetFloat and always get the compiled pass. No texture: the falloff is radial from UV.
Shader "Return/ParticleGlow"
{
    Properties
    {
        _Color ("Color", Color) = (1, 1, 1, 1)
        [Enum(UnityEngine.Rendering.BlendMode)] _DstBlend ("Dst Blend (One additive, OneMinusSrcAlpha alpha)", Float) = 1
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "IgnoreProjector" = "True" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha [_DstBlend]
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
            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; float4 color : COLOR; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float4 color : COLOR; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i)
            {
                V o = (V)0;
                UNITY_SETUP_INSTANCE_ID(i);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.uv = i.uv;
                o.color = i.color;
                return o;
            }
            half4 frag(V i) : SV_Target
            {
                // radial soft falloff from UV, no texture: 0 at the quad edge, 1 at the center
                float d = length(i.uv * 2.0 - 1.0);
                float falloff = smoothstep(1.0, 0.0, d);
                half4 col = i.color * _Color;
                col.a *= falloff;
                return col;
            }
            ENDHLSL
        }
    }
}
