using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.Design
{
    public enum ColorRole
    {
        Canvas, Surface100, Surface200, Surface300, Line, LineStrong, Ink, InkMuted, InkFaint,
        Action, OnAction, OnImage, OnLight, ImageScrim, ImageScrimStrong, Glass, GlassEdge, OnGlass, GlassStrong,
        Sky, SkySoft, Aurora, AuroraSoft, Blossom, BlossomSoft, Sun, SunSoft, Success, SuccessSoft, Danger, DangerSoft, Focus
    }

    /// <summary>Binds the sibling Graphic (Image, TMP_Text, RawImage) to a token role and follows the theme.</summary>
    [ExecuteAlways, RequireComponent(typeof(CanvasRenderer))]
    public class ThemedGraphic : MonoBehaviour
    {
        public ColorRole role = ColorRole.Ink;

        public static Color32 Resolve(ReturnPalette p, ColorRole r)
        {
            switch (r)
            {
                case ColorRole.Canvas: return p.Canvas;
                case ColorRole.Surface100: return p.Surface100;
                case ColorRole.Surface200: return p.Surface200;
                case ColorRole.Surface300: return p.Surface300;
                case ColorRole.Line: return p.Line;
                case ColorRole.LineStrong: return p.LineStrong;
                case ColorRole.Ink: return p.Ink;
                case ColorRole.InkMuted: return p.InkMuted;
                case ColorRole.InkFaint: return p.InkFaint;
                case ColorRole.Action: return p.Action;
                case ColorRole.OnAction: return p.OnAction;
                case ColorRole.OnImage: return p.OnImage;
                case ColorRole.OnLight: return p.OnLight;
                case ColorRole.ImageScrim: return p.ImageScrim;
                case ColorRole.ImageScrimStrong: return p.ImageScrimStrong;
                case ColorRole.Glass: return p.Glass;
                case ColorRole.GlassEdge: return p.GlassEdge;
                case ColorRole.OnGlass: return p.OnGlass;
                case ColorRole.GlassStrong: return p.GlassStrong;
                case ColorRole.Sky: return p.Sky;
                case ColorRole.SkySoft: return p.SkySoft;
                case ColorRole.Aurora: return p.Aurora;
                case ColorRole.AuroraSoft: return p.AuroraSoft;
                case ColorRole.Blossom: return p.Blossom;
                case ColorRole.BlossomSoft: return p.BlossomSoft;
                case ColorRole.Sun: return p.Sun;
                case ColorRole.SunSoft: return p.SunSoft;
                case ColorRole.Success: return p.Success;
                case ColorRole.SuccessSoft: return p.SuccessSoft;
                case ColorRole.Danger: return p.Danger;
                case ColorRole.DangerSoft: return p.DangerSoft;
                default: return p.Focus;
            }
        }

        void OnEnable() { ThemeManager.Changed += Refresh; Refresh(); }
        void OnDisable() { ThemeManager.Changed -= Refresh; }
        void OnValidate() { Refresh(); }

        public void Refresh()
        {
            Color c = Resolve(ThemeManager.Palette, role);
            if (TryGetComponent<TMP_Text>(out var t)) t.color = c;
            else if (TryGetComponent<Graphic>(out var g)) g.color = c;
        }
    }
}
