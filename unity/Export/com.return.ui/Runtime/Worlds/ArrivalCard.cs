using System.Linq;
using System.Threading.Tasks;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The toast that greets you once a world finishes loading: the room's title and who else is here, ~2m ahead at
    /// eye height. Fades in, holds, fades out (3.5s total), then destroys itself. Built from the same SpatialPanel/UI/
    /// ReturnTokens components as PortalCard's label, so it reads like the rest of the app, not a new look.
    /// </summary>
    public class ArrivalCard : MonoBehaviour
    {
        const float FadeSeconds = 0.5f, HoldSeconds = 2.5f; // 0.5 in + 2.5 hold + 0.5 out = 3.5s

        CanvasGroup _cg;

        public static GameObject Show(Room room, string viewerAccountId, Transform head)
        {
            var panel = SpatialPanel.Create("ArrivalCard", 640, 200);
            if (head != null) panel.PlaceInFront(head, 2f, 0f);

            var col = UI.V(panel.rect, "Col", 6, UI.Pad(30, 22), TextAnchor.MiddleCenter); UI.Stretch(col);
            UI.Bg(col, ColorRole.Glass, 36); UI.Border(col, ColorRole.GlassEdge, 36, 2);
            UI.Text(col, room.title, TextStyle.Title, ColorRole.OnGlass, TextAlignmentOptions.Center);

            var others = room.members.Where(m => m.id != viewerAccountId).Select(m => m.name.Split(' ')[0]).ToList();
            if (others.Count > 0)
                UI.Text(col, "with " + string.Join(", ", others), TextStyle.Caption, ColorRole.OnGlass, TextAlignmentOptions.Center);

            var cg = panel.gameObject.AddComponent<CanvasGroup>(); cg.alpha = 0f;
            var card = panel.gameObject.AddComponent<ArrivalCard>(); card._cg = cg;
            card.Run();
            return panel.gameObject;
        }

        async void Run()
        {
            await Fade(1f, FadeSeconds);
            if (this == null) return;
            float t = 0; while (t < HoldSeconds) { t += Time.unscaledDeltaTime; await Task.Yield(); if (this == null) return; }
            await Fade(0f, FadeSeconds);
            if (this != null) Destroy(gameObject);
        }

        async Task Fade(float target, float seconds)
        {
            float from = _cg.alpha, t = 0;
            while (t < seconds)
            {
                t += Time.unscaledDeltaTime;
                _cg.alpha = Mathf.Lerp(from, target, Mathf.SmoothStep(0, 1, t / seconds));
                await Task.Yield();
                if (this == null) return;
            }
            _cg.alpha = target;
        }
    }
}
