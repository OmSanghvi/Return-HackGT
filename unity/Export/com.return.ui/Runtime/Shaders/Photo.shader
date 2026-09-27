// Photographic surfaces for the hub (Runtime/Hub/PhotoGround.cs, Runtime/Hub/DistantTrees.cs): a texture, tinted, either
// tiled in world XZ (ground) or on the mesh UVs (tree impostor cards), with optional alpha cutout, a radial fade by XZ
// distance from the object's origin (so the ground melts into the HDRI's own photographed ground) and scene fog.
// Unlit on purpose: the photos already carry their daylight, and it keeps Quest cheap.
Shader "Return/Photo"
{
    Properties
    {
        _MainTex ("Photo", 2D) = "white" {}
        _Tint ("Tint", Color) = (1, 1, 1, 1)
        _WorldTiling ("World XZ tiling (meters per tile, 0 = mesh UVs)", Float) = 0
        _Cutoff ("Alpha cutoff (0 = off)", Range(0, 1)) = 0
        _FadeInner ("Fade start (m from origin, 0 = no fade)", Float) = 0
        _FadeOuter ("Fade end (m from origin)", Float) = 1
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent-2" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Unlit"
            Tags { "LightMode" = "UniversalForward" }
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite On
            Cull Off
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST, _Tint; float _WorldTiling, _Cutoff, _FadeInner, _FadeOuter;
            CBUFFER_END
            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 world : TEXCOORD1; float fog : TEXCOORD2; UNITY_VERTEX_OUTPUT_STEREO };
            V vert(A i)
            {
                V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.world = TransformObjectToWorld(i.pos.xyz);
                o.pos = TransformWorldToHClip(o.world);
                o.uv = i.uv; o.fog = ComputeFogFactor(o.pos.z);
                return o;
            }
            half4 frag(V i) : SV_Target
            {
                float2 uv = _WorldTiling > 0.0 ? i.world.xz / _WorldTiling : i.uv;
                half4 c = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv) * _Tint;
                if (_Cutoff > 0.0) clip(c.a - _Cutoff);
                if (_FadeInner > 0.0)
                {
                    float3 origin = TransformObjectToWorld(float3(0, 0, 0));
                    c.a *= 1.0 - smoothstep(_FadeInner, _FadeOuter, length(i.world.xz - origin.xz));
                }
                c.rgb = MixFog(c.rgb, i.fog);
                return c;
            }
            ENDHLSL
        }
    }
}
