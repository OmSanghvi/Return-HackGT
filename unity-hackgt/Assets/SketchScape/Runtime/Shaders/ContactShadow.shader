// SketchScape RoomKit: soft contact shadow under a splat (splats cast no shadows).
// Darkens what is below it (black, alpha = mask * strength). Quest single-pass-instanced safe.
Shader "SketchScape/ContactShadow"
{
    Properties
    {
        _MainTex ("Mask (alpha)", 2D) = "white" {}
        _Strength ("Strength", Range(0, 1)) = 0.6
    }
    SubShader
    {
        Tags { "Queue" = "Transparent-30" "RenderType" = "Transparent" "IgnoreProjector" = "True" }
        Pass
        {
            ZWrite Off
            Cull Off
            Offset -1, -1
            Blend SrcAlpha OneMinusSrcAlpha
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            float _Strength;
            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };
            v2f vert (appdata_base v)
            {
                v2f o;
                UNITY_SETUP_INSTANCE_ID(v);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = v.texcoord.xy;
                return o;
            }
            fixed4 frag (v2f i) : SV_Target
            {
                return fixed4(0, 0, 0, tex2D(_MainTex, i.uv).a * _Strength);
            }
            ENDCG
        }
    }
}
