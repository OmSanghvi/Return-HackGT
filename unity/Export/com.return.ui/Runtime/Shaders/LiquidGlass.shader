// Liquid-glass surface for world-space UI panels, chips and buttons: a translucent cool tint (the vertex color that
// ThemedGraphic already writes for the Glass/GlassStrong roles), a soft vertical gradient, a bright rim near the
// rounded edge, a faint diagonal sheen, and a cheap fake blur: the hub sky sampled at a heavy mip through
// screen-space UV (bound globally by HubEnvironment). A real backdrop blur re-blurs the whole sky every frame,
// too costly on Quest 2 (see README "Known limits"); this fakes the frosted read instead.
// Rounding is an SDF in object space (dp units), the same sdBox as Return/SkyParallax. The sprite's own baked
// alpha (Shapes.Rounded/Pill, already anti-aliased on the CPU) is kept as a second mask, so this material still
// looks right if a caller doesn't bother setting _Size/_Radius to match.
Shader "Return/LiquidGlass"
{
    Properties
    {
        _MainTex ("Sprite", 2D) = "white" {}
        _ReturnGlassBlur ("Fake blur source (set globally by HubEnvironment)", 2D) = "grey" {}
        _Size ("Size (w,h dp)", Vector) = (200, 60, 0, 0)
        _Radius ("Corner radius (dp)", Float) = 24
        _Edge ("Edge feather (dp)", Float) = 1.5
        _RimWidth ("Rim width (dp)", Float) = 1.4
        _RimBoost ("Rim brightness", Float) = 0.35
        _SheenStrength ("Sheen strength", Float) = 0.12
        _BlurAmount ("Fake blur mix", Range(0, 1)) = 0.22
        [Enum(UnityEngine.Rendering.CompareFunction)] _ZTest ("ZTest", Float) = 4
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" "IgnoreProjector" = "True" }
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

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            TEXTURE2D(_ReturnGlassBlur); SAMPLER(sampler_ReturnGlassBlur);

            CBUFFER_START(UnityPerMaterial)
                float4 _Size;
                float _Radius, _Edge, _RimWidth, _RimBoost, _SheenStrength, _BlurAmount;
            CBUFFER_END

            struct A { float4 pos : POSITION; float2 uv : TEXCOORD0; float4 color : COLOR; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct V { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float4 color : COLOR; float2 local : TEXCOORD1; UNITY_VERTEX_OUTPUT_STEREO };

            V vert(A i)
            {
                V o = (V)0; UNITY_SETUP_INSTANCE_ID(i); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = TransformObjectToHClip(i.pos.xyz);
                o.uv = i.uv; o.color = i.color; o.local = i.pos.xy; // object-space position in dp, same units as _Size
                return o;
            }

            // Same rounded-box signed distance as Return/SkyParallax's sdBox, centered on the rect, in dp.
            float sdBox(float2 p, float2 b, float r) { float2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }

            half4 frag(V i) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);
                float2 size = max(_Size.xy, 1.0);
                float minSide = min(size.x, size.y);
                float r = clamp(_Radius, 0.0, minSide * 0.5);
                float sd = sdBox(i.local, size * 0.5, r);
                float feather = max(_Edge, fwidth(sd));
                float coverage = 1.0 - smoothstep(-feather, feather, sd);
                float spriteA = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, i.uv).a;
                float alpha = i.color.a * coverage * spriteA;
                if (alpha <= 0.002) discard;

                // subtle vertical gradient: a touch lighter near the top, like light catching the glass
                float grad = lerp(0.94, 1.07, i.uv.y);
                half3 col = i.color.rgb * grad;

                // fake frosted blur: the hub sky, heavily mipped, read through screen-space UV instead of a real re-blur
                float2 screenUV = GetNormalizedScreenSpaceUV(i.pos);
                half3 blur = SAMPLE_TEXTURE2D_LOD(_ReturnGlassBlur, sampler_ReturnGlassBlur, screenUV, 8.0).rgb;
                col = lerp(col, blur, _BlurAmount);

                // rim: a soft bright line just inside the rounded edge
                float rim = (1.0 - smoothstep(0.0, _RimWidth, abs(sd))) * step(sd, 0.0);
                col += rim * _RimBoost;

                // sheen: a faint diagonal band drifting very slowly, like light moving across the glass
                float diag = frac((i.local.x + i.local.y) / max(size.x + size.y, 1.0) * 1.6 + _Time.y * 0.015);
                float sheen = smoothstep(0.42, 0.5, diag) - smoothstep(0.5, 0.58, diag);
                col += sheen * _SheenStrength;

                return half4(col, alpha);
            }
            ENDHLSL
        }
    }
}
