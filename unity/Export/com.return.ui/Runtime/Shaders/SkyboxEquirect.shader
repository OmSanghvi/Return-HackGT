// Real equirectangular skybox (replaces the old painted dome + panorama backdrop). Assigned to RenderSettings.skybox,
// so Unity's own skybox pass feeds it a fixed mesh centered on the camera; the object-space vertex position is
// already a view direction (same trick as Return/SkyGradient). Adds a horizon haze blend toward _HazeColor so the
// graded sky reads as one continuous dreamy scene instead of a hard photo dropped behind the hub.
Shader "Return/SkyboxEquirect"
{
    Properties
    {
        _MainTex ("Equirect sky", 2D) = "grey" {}
        _Tint ("Tint", Color) = (1, 1, 1, 1)
        _Exposure ("Exposure", Range(0, 4)) = 1
        _Rotation ("Rotation (degrees)", Range(0, 360)) = 0
        _HazeColor ("Horizon haze color", Color) = (1, 1, 1, 1)
        _HazeHeight ("Haze height (0..1 of view-up)", Range(0.02, 1)) = 0.15
        _HazeStrength ("Haze strength", Range(0, 1)) = 0.35
    }
    SubShader
    {
        Tags { "RenderType" = "Background" "Queue" = "Background" "RenderPipeline" = "UniversalPipeline" "PreviewType" = "Skybox" }
        Pass
        {
            Name "Unlit"
            // no LightMode tag: URP's skybox draw skips passes tagged UniversalForward (built-in skybox shaders have none)
            Cull Off
            ZWrite Off
            ZTest LEqual

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);

            CBUFFER_START(UnityPerMaterial)
                half4 _Tint, _HazeColor;
                half _Exposure, _Rotation, _HazeHeight, _HazeStrength;
            CBUFFER_END

            struct A { float4 pos : POSITION; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float3 dir : TEXCOORD0; UNITY_VERTEX_OUTPUT_STEREO };

            V vert(A i)
            {
                V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.dir = i.pos.xyz; // skybox mesh is centered on the camera, so object space == view direction
                return o;
            }

            half4 frag(V i) : SV_Target
            {
                float3 d = normalize(i.dir);
                float rad = radians(_Rotation);
                float cs = cos(rad), sn = sin(rad);
                float2 dxz = float2(d.x * cs - d.z * sn, d.x * sn + d.z * cs);
                float2 uv = float2(atan2(dxz.x, dxz.y) / (2.0 * PI) + 0.5, 1.0 - acos(clamp(d.y, -1.0, 1.0)) / PI); // v = 1 is the top row of the image (sky), so straight up maps there
                half3 col = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv).rgb * _Exposure * _Tint.rgb;
                // haze: brightens/pales everything within _HazeHeight of the horizon, strongest right at d.y = 0
                float haze = saturate(1.0 - abs(d.y) / max(_HazeHeight, 0.001));
                col = lerp(col, _HazeColor.rgb, haze * _HazeStrength);
                return half4(col, 1);
            }
            ENDHLSL
        }
    }
}
