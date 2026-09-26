using System.Linq;
using System.Threading.Tasks;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The hub's greeting: the sky wakes with a swell (from black at dusk, from white with a light bloom in day), "Welcome back, &lt;name&gt;" drifts up and dissolves, portals
    /// bloom in one by one with a chime, then a soft nudge toward the ring until the first portal hover or touch.
    /// Only plays on sign-in or first load; returning from a world is just a gentle re-wake, no replay.
    /// Every step re-checks its Unity objects for null each frame: nothing here is awaited by a caller, so it can still be
    /// mid-flight when a test or a scene unload destroys the hub out from under it.
    /// </summary>
    public class HubIntro : MonoBehaviour
    {
        HubController _hub; IRoomStore _store; Transform _head;
        ScreenFade _wake;
        bool _nudgeHidden, _awaitingBloom, _enabledOnce;

        /// <summary>The greeting wakes from black at dusk (the sky was dark) and from white in day (a soft light bloom
        /// brightening into the meadow sky). Same fade, same timings, just which color it clears from.</summary>
        static Color WakeColor => ThemeManager.Current == ReturnTheme.Dusk ? Color.black : Color.white;

        /// <summary>hubRoot is the hub's own visibility root (hidden while in a world); the greeting/nudge panels are parented
        /// under it so they hide and reset together with everything else, instead of floating over a world mid-sequence.</summary>
        public static HubIntro Attach(HubController hub, IRoomStore store, Transform head, Transform hubRoot)
        {
            var go = new GameObject("HubIntro"); go.transform.SetParent(hubRoot != null ? hubRoot : hub.transform, false);
            var it = go.AddComponent<HubIntro>();
            it._hub = hub; it._store = store; it._head = head;
            var camGo = head != null ? (head.GetComponent<Camera>() != null ? head : head.GetComponentInChildren<Camera>()?.transform ?? head) : null;
            it._wake = camGo != null ? ScreenFade.Attach(camGo) : null;
            RoomPortal.AnyHoverOrTouch += it.HideNudge;
            hub.SignedIn += n => _ = it.WelcomeSequence(n.Split(' ')[0]);
            hub.PortalsLaidOut += it.HideUntilBloom; // SignedIn fires before the ring is built, so hide portals as they appear
            if (store.SignedIn) _ = it.WelcomeSequence(FirstName(store));
            return it;
        }

        void OnDestroy() { RoomPortal.AnyHoverOrTouch -= HideNudge; }

        static string FirstName(IRoomStore store)
        {
            foreach (var a in RoomLogic.Accounts) if (a.id == store.CurrentAccountId) return a.name.Split(' ')[0];
            return "";
        }

        /// <summary>This object lives under the hub root, so it re-enables exactly when the hub reappears after a world.</summary>
        void OnEnable() { if (_enabledOnce) _ = ReWake(); _enabledOnce = true; }

        void HideUntilBloom(System.Collections.Generic.IReadOnlyList<RoomPortal> portals)
        {
            if (!_awaitingBloom) return;
            foreach (var p in portals) if (p != null) p.transform.localScale = Vector3.zero;
        }

        static async Task Wait(float seconds) { float t = 0; while (t < seconds) { t += Time.unscaledDeltaTime; await Task.Yield(); } }

        /// <summary>Coming back from a world: a short sky fade, no welcome text or portal bloom.</summary>
        async Task ReWake()
        {
            if (_wake == null) return;
            _wake.SetColor(WakeColor); _wake.SetAlpha(0.6f);
            await FadeWake(0f, 1f);
        }

        /// <summary>Same math as ScreenFade.FadeTo, but re-checks _wake each frame: this runs unawaited, so it can outlive _wake's GameObject.</summary>
        async Task FadeWake(float target, float seconds)
        {
            if (_wake == null) return;
            float from = _wake.Alpha, t = 0;
            while (t < seconds && _wake != null)
            {
                t += Time.unscaledDeltaTime;
                _wake.SetAlpha(Mathf.Lerp(from, target, Mathf.SmoothStep(0, 1, t / seconds)));
                await Task.Yield();
            }
            if (_wake != null) _wake.SetAlpha(target);
        }

        async Task WelcomeSequence(string firstName)
        {
            _awaitingBloom = true;
            if (_hub != null) HideUntilBloom(_hub.Cards.Where(c => c != null).Select(c => c.portal).ToList());
            if (_wake != null)
            {
                _wake.SetColor(WakeColor); _wake.SetAlpha(1f);
                ReturnAudio.Play(ReturnAudio.GreetingSwell, 0.8f);
                _ = FadeWake(0f, 3f);
            }
            await GreetingText(firstName);
            if (_hub == null) return;
            var portals = _hub.Cards.Where(c => c != null).Select(c => c.portal).Where(p => p != null).ToList();
            _awaitingBloom = false;
            await BloomPortals(portals);
            await Nudge();
        }

        async Task GreetingText(string firstName)
        {
            if (this == null || _head == null || string.IsNullOrEmpty(firstName)) return;
            var panel = SpatialPanel.Create("Greeting", 900, 220, transform);
            var fwd = _head.forward; fwd.y = 0; if (fwd.sqrMagnitude < 0.01f) fwd = Vector3.forward; fwd.Normalize();
            var basePos = _head.position + fwd * 2f + Vector3.up * 0.1f;
            panel.transform.position = basePos; panel.transform.rotation = Quaternion.LookRotation(fwd);
            panel.transform.localScale = Vector3.one * 0.0018f;
            var txt = UI.Text(panel.rect, "Welcome back, " + firstName, TextStyle.DisplayM, ColorRole.OnImage, TextAlignmentOptions.Center);
            UI.Stretch(txt.rectTransform);
            txt.alpha = 0f;

            float t = 0, fadeIn = 0.6f;
            while (t < fadeIn && panel != null) { t += Time.unscaledDeltaTime; float x = t / fadeIn; txt.alpha = Mathf.Clamp01(x); panel.transform.position = basePos + Vector3.up * (0.05f * x); await Task.Yield(); }

            t = 0; float hold = 1.3f;
            while (t < hold && panel != null) { t += Time.unscaledDeltaTime; panel.transform.position = basePos + Vector3.up * (0.05f + 0.03f * (t / hold)); await Task.Yield(); }

            t = 0; float fadeOut = 0.6f;
            while (t < fadeOut && panel != null) { t += Time.unscaledDeltaTime; txt.alpha = 1f - Mathf.Clamp01(t / fadeOut); await Task.Yield(); }
            if (panel != null) Destroy(panel.gameObject);
        }

        static readonly Vector3 PortalScale = new Vector3(ReturnSpatial.PortalWidth, ReturnSpatial.PortalHeight, 1);

        async Task BloomPortals(System.Collections.Generic.List<RoomPortal> portals)
        {
            for (int i = 0; i < portals.Count; i++)
            {
                var p = portals[i]; if (p == null) continue;
                ReturnAudio.PlayAt(ReturnAudio.Chime, p.transform.position, 0.3f + i * 0.02f);
                _ = BloomOne(p);
                await Wait(0.25f);
            }
        }

        static async Task BloomOne(RoomPortal p)
        {
            if (p == null) return;
            p.transform.localScale = Vector3.zero;
            float t = 0, dur = 0.35f;
            while (t < dur && p != null) { t += Time.unscaledDeltaTime; p.transform.localScale = PortalScale * EaseOutBack(Mathf.Clamp01(t / dur)); await Task.Yield(); }
            if (p != null) p.transform.localScale = PortalScale;
        }

        static float EaseOutBack(float x) { const float c1 = 1.70158f, c3 = c1 + 1f; float m = x - 1f; return 1f + c3 * m * m * m + c1 * m * m; }

        /// <summary>A soft glass hint below the ring, pulsing until the first portal hover or touch.</summary>
        async Task Nudge()
        {
            if (this == null || _head == null) return;
            _nudgeHidden = false;
            var panel = SpatialPanel.Create("Nudge", 560, 120, transform);
            var fwd = _head.forward; fwd.y = 0; if (fwd.sqrMagnitude < 0.01f) fwd = Vector3.forward; fwd.Normalize();
            panel.transform.position = _head.position + fwd * (ReturnSpatial.PortalRingRadius * 0.85f) + Vector3.down * 0.55f;
            panel.transform.rotation = Quaternion.LookRotation(fwd);
            panel.transform.localScale = Vector3.one * 0.0016f;
            var col = UI.V(panel.rect, "Nudge", 8, UI.Pad(24), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 30); UI.Border(col, ColorRole.GlassEdge, 30, 2);
            UI.Text(col, "Reach toward a world to step in", TextStyle.Body, ColorRole.OnGlass, TextAlignmentOptions.Center);
            var cg = panel.gameObject.AddComponent<CanvasGroup>();

            while (!_nudgeHidden && panel != null) { cg.alpha = 0.55f + 0.35f * (0.5f + 0.5f * Mathf.Sin(Time.unscaledTime * 1.6f)); await Task.Yield(); }

            float t = 0, from = panel != null ? cg.alpha : 0f;
            while (t < 0.4f && panel != null) { t += Time.unscaledDeltaTime; cg.alpha = Mathf.Lerp(from, 0f, t / 0.4f); await Task.Yield(); }
            if (panel != null) Destroy(panel.gameObject);
        }

        void HideNudge() => _nudgeHidden = true;
    }
}
