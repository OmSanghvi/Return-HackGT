using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Every component on one panel, for design review and as a usage reference. Toggle Day/Dusk with the button.</summary>
    public class ComponentGallery : MonoBehaviour
    {
        public Camera viewer;
        public SpatialPanel Panel { get; private set; }
        public SkyBackdrop Backdrop { get; private set; }

        void Start() { Bootstrap(); }
        bool _booted;

        public void Bootstrap()
        {
            if (_booted) return; _booted = true;
            if (viewer == null) viewer = Camera.main;
            var sky = new GameObject("GallerySky"); sky.transform.SetParent(transform, false);
            Backdrop = sky.AddComponent<SkyBackdrop>(); Backdrop.distance = 5.5f; Backdrop.size = new Vector2(13f, 7.3f); Backdrop.Set(SceneKey.Plain, true);

            Panel = SpatialPanel.Create("GalleryPanel", 1500, 1000, transform);
            if (viewer != null) { Panel.PlaceInFront(viewer.transform, 2.0f, 0); Panel.SetEventCamera(viewer); }
            var root = Panel.rect;
            var scroll = UI.Box(root, "Scroll"); UI.Stretch(scroll);
            var view = UI.Box(scroll, "Viewport"); UI.Stretch(view); view.gameObject.AddComponent<RectMask2D>();
            var c = UI.V(view, "Content", 26, new RectOffset(40, 40, 30, 60));
            c.anchorMin = new Vector2(0, 1); c.anchorMax = new Vector2(1, 1); c.pivot = new Vector2(0.5f, 1); c.sizeDelta = Vector2.zero; UI.Fit(c);
            var sr = scroll.gameObject.AddComponent<ScrollRect>(); sr.viewport = view; sr.content = c; sr.horizontal = false; sr.scrollSensitivity = 40;
            var hit = UI.Img(scroll, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(hit.rectTransform); hit.transform.SetAsFirstSibling();

            UI.Text(c, "Return " + UI.Em("UI"), TextStyle.DisplayL, ColorRole.OnImage);
            RButton.Create(Row(c, 56), ThemeManager.Current == ReturnTheme.Dusk ? "Switch to Day" : "Switch to Dusk", BtnVariant.Glass, BtnSize.Md, "moon",
                onClick: () => { ThemeManager.SetOverride(ThemeManager.Current == ReturnTheme.Dusk ? ReturnTheme.Day : ReturnTheme.Dusk); });

            Section(c, "Buttons", card =>
            {
                var r = Row(card); foreach (BtnVariant v in System.Enum.GetValues(typeof(BtnVariant))) RButton.Create(r, v.ToString(), v);
                var r2 = Row(card); RButton.Create(r2, "Small", BtnVariant.Primary, BtnSize.Sm); RButton.Create(r2, "Medium", BtnVariant.Primary, BtnSize.Md, "plus"); RButton.Create(r2, "Large arrow", BtnVariant.Primary, BtnSize.Lg, arrow: true);
            });
            Section(c, "Field", card => { RField.Create(card, "Name this room", "The lake house, summer 2019", "Shown on the room's card."); var e = RField.Create(card, "With error", "Room name"); e.SetError("Give the room a name."); });
            Section(c, "Status tags", card => { var r = Row(card); foreach (RoomStatus s in System.Enum.GetValues(typeof(RoomStatus))) StatusTag.Create(r, s); });
            Section(c, "Presence and avatars", card =>
            {
                PresenceStack.Create(card, new[] { new Who("Dylan Houle", true), new Who("Mom"), new Who("Sam Park"), new Who("Ava Lin"), new Who("Jordan Reyes") }, 4, 56, true);
                var r = Row(card); Nameplate.Create(r, "Sam Park"); Eyebrow.Create(r, "Ready", "Built from 15 photos");
            });
            Section(c, "Stepper and progress", card => { Stepper.Create(card, 1); var b = Bar.Create(card, ColorRole.Sun, 10); b.Set(0.6f); });
            Section(c, "Member list", card => MemberList.Create(card, RoomUploadScreen.Rows(RoomLogic.Seed(System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())[1], System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), m => { }));
            Section(c, "Room cards", card =>
            {
                var g = UI.Box(card, "Grid"); var gl = g.gameObject.AddComponent<GridLayoutGroup>(); gl.cellSize = new Vector2(RoomCard.W, RoomCard.H); gl.spacing = new Vector2(24, 24); UI.Fit(g);
                var rooms = RoomLogic.Seed(System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                for (int i = 0; i < 3; i++)
                {
                    var r = rooms[i]; var (st, txt, meta) = DashboardScreen.CardInfo(r);
                    RoomCard.Create(g, RoomCard.CoverOf(r), r.title, meta, st, txt, r.members.ConvertAll(m => new Who(m.name)).ToArray(), () => { }, () => { });
                }
            });
            Section(c, "Develop progress", card => { var h = DevelopProgress.Create(card, UIAssets.Sky(SceneKey.Beach), "Last day of summer", 0.5f); });
            Section(c, "Photo drop", card => PhotoDrop.Create(card, new System.Collections.Generic.List<string> { "Home", "Meadow" }, 12, null));
            Section(c, "Hand menu and portal window", card =>
            {
                var r = Row(card, 280); HandMenu.Create(r, new[] { new HandMenu.Item("home", "Rooms", null), new HandMenu.Item("play", "Advance", null), new HandMenu.Item("moon", "Theme", null) });
                PortalWindow.Create(r, UIAssets.Sky(SceneKey.Meadow), 200, 266, null);
            });
        }

        static RectTransform Row(Transform p, float h = 68) { var r = UI.H(p, "Row", 12, null, TextAnchor.MiddleLeft); UI.Size(r, -1, h); return r; }

        static void Section(Transform parent, string title, System.Action<RectTransform> fill)
        {
            var card = UI.V(parent, "Section:" + title, 14, UI.Pad(28));
            UI.Bg(card, ColorRole.GlassStrong, 32); UI.Border(card, ColorRole.GlassEdge, 32, 2);
            UI.Text(card, title, TextStyle.Overline, ColorRole.InkMuted);
            fill(card);
        }
    }
}
