using System;
using UnityEngine;

namespace Return.Design
{
    /// <summary>Day/Dusk switch. Dusk 19:00-06:00 by default; Override pins a theme; Forced wins over both (Ready screen, VR chapter).</summary>
    public static class ThemeManager
    {
        public static event Action Changed;

        static ReturnTheme? _override, _forced;

        public static ReturnTheme Current => _forced ?? _override ?? ByClock();
        public static ReturnPalette Palette => ReturnColors.Get(Current);

        public static void SetOverride(ReturnTheme? t) => Apply(ref _override, t);
        public static void SetForced(ReturnTheme? t) => Apply(ref _forced, t);

        static ReturnTheme ByClock()
        {
            int h = DateTime.Now.Hour;
            return h >= 19 || h < 6 ? ReturnTheme.Dusk : ReturnTheme.Day;
        }

        static void Apply(ref ReturnTheme? field, ReturnTheme? value)
        {
            var before = Current;
            field = value;
            if (Current != before) Changed?.Invoke();
        }
    }
}
