// SketchScape RoomKit: floor apron that continues the floor texture past the solid floor and
// fades it out radially, so the floor dissolves into the HDRI instead of ending in a hard edge.
// UVs are world-space (xz * _Tiling), matching the RoomKit floor mesh.
Shader "SketchScape/FloorFade"
{
    Properties
    {
        _Color ("Color", Color) = (1, 1, 1, 1)
        _MainTex ("Albedo", 2D) = "white" {}
        _Glossiness ("Smoothness", Range(0, 1)) = 0.15
        _FadeCenter ("Fade Center (xz)", Vector) = (0, 0, 0, 0)
        _FadeInner ("Fade Start Radius", Float) = 6
        _FadeOuter ("Fade End Radius", Float) = 12
        _WorldTiling ("Texture repeats per metre", Float) = 0.5
    }
    SubShader
    {
        Tags { "Queue" = "Transparent-20" "RenderType" = "Transparent" "IgnoreProjector" = "True" }
        LOD 200
        ZWrite Off
        CGPROGRAM
        #pragma surface surf Standard alpha:fade
        #pragma target 3.0
        sampler2D _MainTex;
        fixed4 _Color;
        half _Glossiness;
        float4 _FadeCenter;
        float _FadeInner, _FadeOuter, _WorldTiling;
        struct Input { float3 worldPos; };
        void surf (Input IN, inout SurfaceOutputStandard o)
        {
            float2 uv = IN.worldPos.xz * _WorldTiling;
            fixed4 c = tex2D(_MainTex, uv) * _Color;
            float d = distance(IN.worldPos.xz, _FadeCenter.xy);
            o.Albedo = c.rgb;
            o.Smoothness = _Glossiness;
            o.Metallic = 0;
            o.Alpha = 1 - smoothstep(_FadeInner, _FadeOuter, d);
        }
        ENDCG
    }
    FallBack Off
}
