// return design tokens for Unity. Generated from tokens.json; edit that, not this.
// Two themes: Day (default) and Dusk. Use ReturnColors.Current(theme) or the themed classes directly.
using UnityEngine;

namespace Return.Design
{
    public enum ReturnTheme { Day, Dusk }

    /// <summary>Every field here mirrors the like-named variable in web-app/src/design-system/tokens.css exactly
    /// (CamelCase here, kebab-case there: Glass -> --glass, SkyTop -> --sky-top, and so on); keep the numbers identical
    /// so the VR hub and the web app read as one product. See ReturnColorsDusk below for the dusk theme's :root[data-theme="dusk"] block.</summary>
    public static class ReturnColorsDay
    {
        /// <summary>Page ground around framed imagery (the warm cloud-white margin in day, deep night blue in dusk).</summary>
        public static readonly Color32 Canvas = new Color32(237, 234, 228, 255);
        /// <summary>Plain content areas: settings, long lists, anywhere without imagery.</summary>
        public static readonly Color32 Surface100 = new Color32(246, 244, 240, 255);
        /// <summary>Cards and sheets on plain areas.</summary>
        public static readonly Color32 Surface200 = new Color32(255, 255, 255, 255);
        /// <summary>Hover, selected rows, pressed states on plain surfaces.</summary>
        public static readonly Color32 Surface300 = new Color32(235, 231, 224, 255);
        /// <summary>Decorative dividers on plain surfaces. Not for control borders.</summary>
        public static readonly Color32 Line = new Color32(217, 212, 204, 255);
        /// <summary>Control borders on plain surfaces (inputs, secondary buttons). 3.2:1 or better on every surface in both themes.</summary>
        public static readonly Color32 LineStrong = new Color32(125, 120, 107, 255);
        /// <summary>Primary text on canvas, surface-100/200/300 and glass-strong (12:1 or better in both themes).</summary>
        public static readonly Color32 Ink = new Color32(20, 26, 43, 255);
        /// <summary>Secondary text and metadata on any plain surface or glass-strong (6.1:1 or better).</summary>
        public static readonly Color32 InkMuted = new Color32(74, 81, 102, 255);
        /// <summary>Placeholders and disabled labels on any plain surface (4.6:1 or better). Never for content needed to act.</summary>
        public static readonly Color32 InkFaint = new Color32(95, 101, 122, 255);
        /// <summary>Primary button fill on plain surfaces and glass-strong. One per view.</summary>
        public static readonly Color32 Action = new Color32(20, 26, 43, 255);
        /// <summary>Label and icon on an action fill (15:1 or better).</summary>
        public static readonly Color32 OnAction = new Color32(255, 255, 255, 255);
        /// <summary>All text, icons and outlines placed directly on imagery or light glass. Always over image-scrim or with the text shadow from bundle.css.</summary>
        public static readonly Color32 OnImage = new Color32(255, 255, 255, 255);
        /// <summary>Text and icons on white elements placed over imagery (the light button, the eyebrow badge, a white icon button) in both themes (17:1).</summary>
        public static readonly Color32 OnLight = new Color32(20, 26, 43, 255);
        /// <summary>Scrim behind on-image display text (headlines, card titles): radial center scrim or bottom gradient. Gets bright skies to 3:1 or better for text 24px and up.</summary>
        public static readonly Color32 ImageScrim = new Color32(12, 16, 32, 97);
        /// <summary>Scrim behind small on-image text (body, captions, card meta): the bottom of card and hero gradients. Use when on-image text is under 24px.</summary>
        public static readonly Color32 ImageScrimStrong = new Color32(12, 16, 32, 148);
        /// <summary>Glass over imagery: nav pill, glass buttons, chips, hand menu. Always with glass-blur. Text on it is on-glass. Day glass is light frosted, dusk glass is smoked, so text stays readable on any sky.</summary>
        public static readonly Color32 Glass = new Color32(255, 255, 255, 148);
        /// <summary>1px border of any glass element over imagery.</summary>
        public static readonly Color32 GlassEdge = new Color32(255, 255, 255, 191);
        /// <summary>Text and icons on glass. Ink on day's light glass, white on dusk's smoked glass.</summary>
        public static readonly Color32 OnGlass = new Color32(20, 26, 43, 255);
        /// <summary>Frosted panels that hold real content over imagery (share sheet, VR panel, dropzone). Text on it is ink / ink-muted.</summary>
        public static readonly Color32 GlassStrong = new Color32(250, 248, 244, 199);
        /// <summary>Links, selection and the default accent on plain surfaces and glass-strong (5.1:1 or better).</summary>
        public static readonly Color32 Sky = new Color32(47, 95, 168, 255);
        /// <summary>Tinted ground behind sky text: selected tab, info chip.</summary>
        public static readonly Color32 SkySoft = new Color32(227, 236, 248, 255);
        /// <summary>The connective color: other people, presence, invites, shared. Only for people. Text on plain surfaces or aurora-soft.</summary>
        public static readonly Color32 Aurora = new Color32(15, 104, 102, 255);
        /// <summary>Tinted ground behind aurora text: shared chip, a person who is here now.</summary>
        public static readonly Color32 AuroraSoft = new Color32(223, 243, 241, 255);
        /// <summary>Highlight: the 'New' chip, a room's anniversary, an invitation, favorite. Use rarely. Text on plain surfaces or blossom-soft.</summary>
        public static readonly Color32 Blossom = new Color32(165, 58, 102, 255);
        /// <summary>Tinted ground behind blossom text.</summary>
        public static readonly Color32 BlossomSoft = new Color32(248, 230, 238, 255);
        /// <summary>A room that's building: developing status and progress. Text on plain surfaces or sun-soft.</summary>
        public static readonly Color32 Sun = new Color32(133, 84, 0, 255);
        /// <summary>Tinted ground behind sun text.</summary>
        public static readonly Color32 SunSoft = new Color32(248, 236, 212, 255);
        /// <summary>Ready / done. Always with a check icon and a word.</summary>
        public static readonly Color32 Success = new Color32(39, 108, 66, 255);
        /// <summary>Tinted ground behind success text.</summary>
        public static readonly Color32 SuccessSoft = new Color32(226, 241, 231, 255);
        /// <summary>Failed or destructive. Always with an alert icon and a word.</summary>
        public static readonly Color32 Danger = new Color32(178, 58, 51, 255);
        /// <summary>Tinted ground behind danger text.</summary>
        public static readonly Color32 DangerSoft = new Color32(249, 227, 224, 255);
        /// <summary>Keyboard focus ring on plain surfaces and glass-strong: 2px solid, offset 2px. Over imagery the ring is on-image with a dark halo (see bundle.css).</summary>
        public static readonly Color32 Focus = new Color32(47, 95, 168, 255);
        /// <summary>Top stop of the sky gradient used when no image is loaded, and for the VR hub skybox tint.</summary>
        public static readonly Color32 SkyTop = new Color32(143, 185, 230, 255);
        /// <summary>Bottom stop of the sky gradient (horizon haze).</summary>
        public static readonly Color32 SkyBottom = new Color32(243, 230, 222, 255);
    }

    public static class ReturnColorsDusk
    {
        /// <summary>Page ground around framed imagery (the warm cloud-white margin in day, deep night blue in dusk).</summary>
        public static readonly Color32 Canvas = new Color32(10, 15, 31, 255);
        /// <summary>Plain content areas: settings, long lists, anywhere without imagery.</summary>
        public static readonly Color32 Surface100 = new Color32(17, 23, 45, 255);
        /// <summary>Cards and sheets on plain areas.</summary>
        public static readonly Color32 Surface200 = new Color32(25, 32, 61, 255);
        /// <summary>Hover, selected rows, pressed states on plain surfaces.</summary>
        public static readonly Color32 Surface300 = new Color32(35, 43, 77, 255);
        /// <summary>Decorative dividers on plain surfaces. Not for control borders.</summary>
        public static readonly Color32 Line = new Color32(44, 53, 96, 255);
        /// <summary>Control borders on plain surfaces (inputs, secondary buttons). 3.2:1 or better on every surface in both themes.</summary>
        public static readonly Color32 LineStrong = new Color32(111, 120, 168, 255);
        /// <summary>Primary text on canvas, surface-100/200/300 and glass-strong (12:1 or better in both themes).</summary>
        public static readonly Color32 Ink = new Color32(238, 240, 250, 255);
        /// <summary>Secondary text and metadata on any plain surface or glass-strong (6.1:1 or better).</summary>
        public static readonly Color32 InkMuted = new Color32(179, 184, 212, 255);
        /// <summary>Placeholders and disabled labels on any plain surface (4.6:1 or better). Never for content needed to act.</summary>
        public static readonly Color32 InkFaint = new Color32(142, 148, 180, 255);
        /// <summary>Primary button fill on plain surfaces and glass-strong. One per view.</summary>
        public static readonly Color32 Action = new Color32(244, 241, 234, 255);
        /// <summary>Label and icon on an action fill (15:1 or better).</summary>
        public static readonly Color32 OnAction = new Color32(20, 26, 43, 255);
        /// <summary>All text, icons and outlines placed directly on imagery or light glass. Always over image-scrim or with the text shadow from bundle.css.</summary>
        public static readonly Color32 OnImage = new Color32(255, 255, 255, 255);
        /// <summary>Text and icons on white elements placed over imagery (the light button, the eyebrow badge, a white icon button) in both themes (17:1).</summary>
        public static readonly Color32 OnLight = new Color32(20, 26, 43, 255);
        /// <summary>Scrim behind on-image display text (headlines, card titles): radial center scrim or bottom gradient. Gets bright skies to 3:1 or better for text 24px and up.</summary>
        public static readonly Color32 ImageScrim = new Color32(6, 9, 20, 128);
        /// <summary>Scrim behind small on-image text (body, captions, card meta): the bottom of card and hero gradients. Use when on-image text is under 24px.</summary>
        public static readonly Color32 ImageScrimStrong = new Color32(6, 9, 20, 168);
        /// <summary>Glass over imagery: nav pill, glass buttons, chips, hand menu. Always with glass-blur. Text on it is on-glass. Day glass is light frosted, dusk glass is smoked, so text stays readable on any sky.</summary>
        public static readonly Color32 Glass = new Color32(10, 14, 30, 107);
        /// <summary>1px border of any glass element over imagery.</summary>
        public static readonly Color32 GlassEdge = new Color32(255, 255, 255, 56);
        /// <summary>Text and icons on glass. Ink on day's light glass, white on dusk's smoked glass.</summary>
        public static readonly Color32 OnGlass = new Color32(255, 255, 255, 255);
        /// <summary>Frosted panels that hold real content over imagery (share sheet, VR panel, dropzone). Text on it is ink / ink-muted.</summary>
        public static readonly Color32 GlassStrong = new Color32(17, 23, 45, 189);
        /// <summary>Links, selection and the default accent on plain surfaces and glass-strong (5.1:1 or better).</summary>
        public static readonly Color32 Sky = new Color32(156, 194, 255, 255);
        /// <summary>Tinted ground behind sky text: selected tab, info chip.</summary>
        public static readonly Color32 SkySoft = new Color32(28, 44, 82, 255);
        /// <summary>The connective color: other people, presence, invites, shared. Only for people. Text on plain surfaces or aurora-soft.</summary>
        public static readonly Color32 Aurora = new Color32(127, 227, 223, 255);
        /// <summary>Tinted ground behind aurora text: shared chip, a person who is here now.</summary>
        public static readonly Color32 AuroraSoft = new Color32(18, 53, 60, 255);
        /// <summary>Highlight: the 'New' chip, a room's anniversary, an invitation, favorite. Use rarely. Text on plain surfaces or blossom-soft.</summary>
        public static readonly Color32 Blossom = new Color32(243, 169, 201, 255);
        /// <summary>Tinted ground behind blossom text.</summary>
        public static readonly Color32 BlossomSoft = new Color32(58, 32, 55, 255);
        /// <summary>A room that's building: developing status and progress. Text on plain surfaces or sun-soft.</summary>
        public static readonly Color32 Sun = new Color32(245, 200, 106, 255);
        /// <summary>Tinted ground behind sun text.</summary>
        public static readonly Color32 SunSoft = new Color32(58, 47, 22, 255);
        /// <summary>Ready / done. Always with a check icon and a word.</summary>
        public static readonly Color32 Success = new Color32(143, 217, 168, 255);
        /// <summary>Tinted ground behind success text.</summary>
        public static readonly Color32 SuccessSoft = new Color32(22, 53, 42, 255);
        /// <summary>Failed or destructive. Always with an alert icon and a word.</summary>
        public static readonly Color32 Danger = new Color32(255, 157, 146, 255);
        /// <summary>Tinted ground behind danger text.</summary>
        public static readonly Color32 DangerSoft = new Color32(61, 29, 34, 255);
        /// <summary>Keyboard focus ring on plain surfaces and glass-strong: 2px solid, offset 2px. Over imagery the ring is on-image with a dark halo (see bundle.css).</summary>
        public static readonly Color32 Focus = new Color32(185, 211, 255, 255);
        /// <summary>Top stop of the sky gradient used when no image is loaded, and for the VR hub skybox tint.</summary>
        public static readonly Color32 SkyTop = new Color32(27, 33, 80, 255);
        /// <summary>Bottom stop of the sky gradient (horizon haze).</summary>
        public static readonly Color32 SkyBottom = new Color32(74, 58, 110, 255);
    }

    /// <summary>Theme-switched access: ReturnColors.Get(theme).Ink etc.</summary>
    public sealed class ReturnPalette
    {
        public Color32 Canvas;
        public Color32 Surface100;
        public Color32 Surface200;
        public Color32 Surface300;
        public Color32 Line;
        public Color32 LineStrong;
        public Color32 Ink;
        public Color32 InkMuted;
        public Color32 InkFaint;
        public Color32 Action;
        public Color32 OnAction;
        public Color32 OnImage;
        public Color32 OnLight;
        public Color32 ImageScrim;
        public Color32 ImageScrimStrong;
        public Color32 Glass;
        public Color32 GlassEdge;
        public Color32 OnGlass;
        public Color32 GlassStrong;
        public Color32 Sky;
        public Color32 SkySoft;
        public Color32 Aurora;
        public Color32 AuroraSoft;
        public Color32 Blossom;
        public Color32 BlossomSoft;
        public Color32 Sun;
        public Color32 SunSoft;
        public Color32 Success;
        public Color32 SuccessSoft;
        public Color32 Danger;
        public Color32 DangerSoft;
        public Color32 Focus;
        public Color32 SkyTop;
        public Color32 SkyBottom;
    }

    public static class ReturnColors
    {
        public static readonly ReturnPalette Day = new ReturnPalette {
            Canvas = ReturnColorsDay.Canvas,
            Surface100 = ReturnColorsDay.Surface100,
            Surface200 = ReturnColorsDay.Surface200,
            Surface300 = ReturnColorsDay.Surface300,
            Line = ReturnColorsDay.Line,
            LineStrong = ReturnColorsDay.LineStrong,
            Ink = ReturnColorsDay.Ink,
            InkMuted = ReturnColorsDay.InkMuted,
            InkFaint = ReturnColorsDay.InkFaint,
            Action = ReturnColorsDay.Action,
            OnAction = ReturnColorsDay.OnAction,
            OnImage = ReturnColorsDay.OnImage,
            OnLight = ReturnColorsDay.OnLight,
            ImageScrim = ReturnColorsDay.ImageScrim,
            ImageScrimStrong = ReturnColorsDay.ImageScrimStrong,
            Glass = ReturnColorsDay.Glass,
            GlassEdge = ReturnColorsDay.GlassEdge,
            OnGlass = ReturnColorsDay.OnGlass,
            GlassStrong = ReturnColorsDay.GlassStrong,
            Sky = ReturnColorsDay.Sky,
            SkySoft = ReturnColorsDay.SkySoft,
            Aurora = ReturnColorsDay.Aurora,
            AuroraSoft = ReturnColorsDay.AuroraSoft,
            Blossom = ReturnColorsDay.Blossom,
            BlossomSoft = ReturnColorsDay.BlossomSoft,
            Sun = ReturnColorsDay.Sun,
            SunSoft = ReturnColorsDay.SunSoft,
            Success = ReturnColorsDay.Success,
            SuccessSoft = ReturnColorsDay.SuccessSoft,
            Danger = ReturnColorsDay.Danger,
            DangerSoft = ReturnColorsDay.DangerSoft,
            Focus = ReturnColorsDay.Focus,
            SkyTop = ReturnColorsDay.SkyTop,
            SkyBottom = ReturnColorsDay.SkyBottom,
        };
        public static readonly ReturnPalette Dusk = new ReturnPalette {
            Canvas = ReturnColorsDusk.Canvas,
            Surface100 = ReturnColorsDusk.Surface100,
            Surface200 = ReturnColorsDusk.Surface200,
            Surface300 = ReturnColorsDusk.Surface300,
            Line = ReturnColorsDusk.Line,
            LineStrong = ReturnColorsDusk.LineStrong,
            Ink = ReturnColorsDusk.Ink,
            InkMuted = ReturnColorsDusk.InkMuted,
            InkFaint = ReturnColorsDusk.InkFaint,
            Action = ReturnColorsDusk.Action,
            OnAction = ReturnColorsDusk.OnAction,
            OnImage = ReturnColorsDusk.OnImage,
            OnLight = ReturnColorsDusk.OnLight,
            ImageScrim = ReturnColorsDusk.ImageScrim,
            ImageScrimStrong = ReturnColorsDusk.ImageScrimStrong,
            Glass = ReturnColorsDusk.Glass,
            GlassEdge = ReturnColorsDusk.GlassEdge,
            OnGlass = ReturnColorsDusk.OnGlass,
            GlassStrong = ReturnColorsDusk.GlassStrong,
            Sky = ReturnColorsDusk.Sky,
            SkySoft = ReturnColorsDusk.SkySoft,
            Aurora = ReturnColorsDusk.Aurora,
            AuroraSoft = ReturnColorsDusk.AuroraSoft,
            Blossom = ReturnColorsDusk.Blossom,
            BlossomSoft = ReturnColorsDusk.BlossomSoft,
            Sun = ReturnColorsDusk.Sun,
            SunSoft = ReturnColorsDusk.SunSoft,
            Success = ReturnColorsDusk.Success,
            SuccessSoft = ReturnColorsDusk.SuccessSoft,
            Danger = ReturnColorsDusk.Danger,
            DangerSoft = ReturnColorsDusk.DangerSoft,
            Focus = ReturnColorsDusk.Focus,
            SkyTop = ReturnColorsDusk.SkyTop,
            SkyBottom = ReturnColorsDusk.SkyBottom,
        };
        public static ReturnPalette Get(ReturnTheme theme) { return theme == ReturnTheme.Dusk ? Dusk : Day; }
    }

    /// <summary>Motion. Seconds.</summary>
    public static class ReturnMotion
    {
        /// <summary>Hover, press, focus.</summary>
        public const float Fast = 0.16f;
        /// <summary>Sheets, chips, small reveals.</summary>
        public const float Base = 0.32f;
        /// <summary>Mist clearing: text and images resolving from blur to sharp on first view.</summary>
        public const float Reveal = 1.4f;
        /// <summary>A generated scene resolving once ready (DevelopProgress).</summary>
        public const float Develop = 2.2f;
        /// <summary>VR and web: stepping into a room. Fade through white-out (day) or deep blue (dusk), never a cut.</summary>
        public const float Enter = 2.8f;
        /// <summary>Ambient cloud drift loop on hero imagery.</summary>
        public const float Drift = 60.0f;
        /// <summary>ease-out cubic-bezier(0.16, 1, 0.3, 1): everything that arrives.</summary>
        public static readonly Vector4 EaseOut = new Vector4(0.16f, 1f, 0.3f, 1f);
        /// <summary>ease-in-out cubic-bezier(0.65, 0, 0.35, 1): scene transitions and drift.</summary>
        public static readonly Vector4 EaseInOut = new Vector4(0.65f, 0f, 0.35f, 1f);
    }

    /// <summary>VR measurements. Meters unless named Dp (panel-scale units).</summary>
    public static class ReturnSpatial
    {
        /// <summary>Default ray/pinch panel distance (0.8m to 3m).</summary>
        public const float PanelDistanceRay = 1.2f;
        /// <summary>Closest ray/pinch panel.</summary>
        public const float PanelDistanceRayMin = 0.8f;
        /// <summary>Farthest ray/pinch panel.</summary>
        public const float PanelDistanceRayMax = 3f;
        /// <summary>Direct-poke panels: 42 to 46cm.</summary>
        public const float PanelDistanceTouch = 0.44f;
        /// <summary>Default SpatialPanel width.</summary>
        public const float PanelWidthDp = 1024f;
        /// <summary>Default SpatialPanel height.</summary>
        public const float PanelHeightDp = 640f;
        /// <summary>Minimum panel width.</summary>
        public const float PanelMinWidthDp = 384f;
        /// <summary>Minimum panel height.</summary>
        public const float PanelMinHeightDp = 500f;
        /// <summary>radius-frame.</summary>
        public const float PanelCornerRadiusDp = 32f;
        /// <summary>space-5.</summary>
        public const float PanelPaddingDp = 24f;
        /// <summary>Smallest hit target.</summary>
        public const float TargetMinDp = 48f;
        /// <summary>Minimum gap between targets (12mm).</summary>
        public const float TargetGap = 0.012f;
        /// <summary>Poke travel (7mm).</summary>
        public const float PressDepth = 0.007f;
        /// <summary>RoomPortal arched window width.</summary>
        public const float PortalWidth = 0.9f;
        /// <summary>RoomPortal height.</summary>
        public const float PortalHeight = 1.2f;
        /// <summary>Portals float on an arc this far from the viewer.</summary>
        public const float PortalRingRadius = 2.4f;
        /// <summary>Portal bob amplitude (2cm over 6s).</summary>
        public const float PortalBob = 0.02f;
        /// <summary>Nameplate height above the head.</summary>
        public const float NameplateOffset = 0.28f;
    }

    /// <summary>Spatial type sizes in dp at panel scale. Never italic in-headset.</summary>
    public static class ReturnType
    {
        /// <summary>VR only for room names on portals and panel titles 32dp and up. Roman, never italic.</summary>
        public const float VrDisplaySizeDp = 48f;
        /// <summary>VR section titles. Sizes are dp at panel scale (Meta Horizon OS units).</summary>
        public const float VrH1SizeDp = 32f;
        /// <summary>Nameplates, list headers in VR.</summary>
        public const float VrH2SizeDp = 24f;
        /// <summary>All VR reading text. 18dp is the comfortable floor.</summary>
        public const float VrBodySizeDp = 18f;
        /// <summary>VR metadata. 14dp hard minimum.</summary>
        public const float VrCaptionSizeDp = 14f;
        public const float ReadingFloorDp = 18f;
        public const float MinimumDp = 14f;
    }
}
