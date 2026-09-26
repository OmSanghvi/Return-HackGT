using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Four chapters over four paintings, stepped with the arrows or dots (the web scrolls; a headset steps).</summary>
    public class LandingScreen : RoutedScreen
    {
        struct Chapter { public SceneKey scene; public string kicker, title, body; }
        static readonly Chapter[] Chapters =
        {
            new Chapter { scene = SceneKey.Meadow, kicker = "return", title = "Walk back into the " + "{moments}" + " you miss", body = "Start a room, invite the people who were there, and everyone adds their photos. return rebuilds the place as a world you can stand inside together." },
            new Chapter { scene = SceneKey.Home, kicker = "1 of 3", title = "Start a {room}", body = "Name the place and the moment. Invite the people who were there by email." },
            new Chapter { scene = SceneKey.Beach, kicker = "2 of 3", title = "Everyone adds their {view}", body = "Each person brings their own photos and a note. More angles build a fuller world." },
            new Chapter { scene = SceneKey.CloudSea, kicker = "3 of 3", title = "Step inside {together}", body = "When everyone is in, the room appears in each headset, and you are back." },
        };

        int _chapter;
        RectTransform _body;

        static string Accent(string t) { int a = t.IndexOf('{'), b = t.IndexOf('}'); return a < 0 ? t : t.Substring(0, a) + UI.Em(t.Substring(a + 1, b - a - 1)) + t.Substring(b + 1); }

        public override void Build()
        {
            var scrim = UI.Img(root, "Scrim", ColorRole.ImageScrimStrong, Shapes.GradientUp); scrim.rectTransform.localScale = new Vector3(1, -1, 1); UI.Stretch(scrim.rectTransform, -420, -260, -420, 120);
            var scrim2 = UI.Img(root, "Scrim2", ColorRole.ImageScrim, Shapes.GradientUp); scrim2.rectTransform.localScale = new Vector3(1, -1, 1); UI.Stretch(scrim2.rectTransform, -420, -260, -420, 320);
            var wrap = UI.Box(root, "NavWrap"); wrap.anchorMin = new Vector2(0, 1); wrap.anchorMax = new Vector2(1, 1); wrap.pivot = new Vector2(0.5f, 1); wrap.sizeDelta = new Vector2(-64, 68); wrap.anchoredPosition = new Vector2(0, -28);
            var nav = GlassNav.Create(wrap, new[] { new NavItem("How it works", () => SetChapter(1)), new NavItem("Rooms", () => app.router.Go(Route.Dashboard)) }, row =>
            {
                if (!app.store.SignedIn) RButton.Create(row, "Sign in", BtnVariant.Ghost, BtnSize.Sm, onClick: () => app.router.Go(Route.SignIn));
                RButton.Create(row, "Create a room", BtnVariant.Primary, BtnSize.Sm, "plus", onClick: () => app.router.Go(Route.CreateRoom));
            });
            UI.Stretch(nav);
            _body = UI.V(root, "Body", 16, new RectOffset(72, 72, 0, 72), TextAnchor.LowerLeft); UI.Stretch(_body);
            SetChapter(0);
        }

        void SetChapter(int i)
        {
            _chapter = i;
            var c = Chapters[i];
            app.backdrop.Set(c.scene);
            foreach (Transform t in _body) Object.Destroy(t.gameObject);
            UI.Text(_body, c.kicker, TextStyle.Kicker, ColorRole.OnImage);
            var title = UI.Text(_body, Accent(c.title), i == 0 ? TextStyle.Hero : TextStyle.DisplayL, ColorRole.OnImage); UI.Size(title.rectTransform, 860);
            var body = UI.Text(_body, c.body, TextStyle.BodyL, ColorRole.OnImage); UI.Size(body.rectTransform, 700);
            UI.Spacer(_body, 0, 8);
            var actions = Row(_body, 14, 64);
            if (i == 0)
            {
                RButton.Create(actions, "Create a room", BtnVariant.Light, BtnSize.Lg, "plus", onClick: () => app.router.Go(Route.CreateRoom));
                RButton.Create(actions, "See how it works", BtnVariant.Glass, BtnSize.Lg, onClick: () => SetChapter(1));
            }
            else
            {
                RButton.Create(actions, "Back", BtnVariant.Glass, BtnSize.Lg, "back", onClick: () => SetChapter(_chapter - 1));
                if (i < Chapters.Length - 1) RButton.Create(actions, "Next", BtnVariant.Light, BtnSize.Lg, arrow: true, onClick: () => SetChapter(_chapter + 1));
                else RButton.Create(actions, "Create a room", BtnVariant.Light, BtnSize.Lg, "plus", onClick: () => app.router.Go(Route.CreateRoom));
            }
            var dots = Row(_body, 8, 20);
            for (int d = 0; d < Chapters.Length; d++)
            {
                var dot = UI.Img(dots, "Dot", ColorRole.OnImage, Shapes.Pill, Image.Type.Sliced, true); UI.Size(dot.rectTransform, d == i ? 34 : 12, 12); dot.color = new Color(1, 1, 1, d == i ? 1f : 0.5f); dot.GetComponent<ThemedGraphic>().enabled = false;
                int k = d; dot.gameObject.AddComponent<Pressable>().onClick = () => SetChapter(k);
            }
            LayoutRebuilder.ForceRebuildLayoutImmediate(_body);
        }
    }

    public class SignInScreen : RoutedScreen
    {
        public override void Build()
        {
            app.backdrop.Set(SceneKey.Clouds);
            var logo = UI.Img(root, "Logo", ColorRole.OnImage, UIAssets.Logo("return-lockup-white")); logo.preserveAspect = true; logo.color = Color.white; logo.GetComponent<ThemedGraphic>().enabled = false;
            UI.Anchor(logo.rectTransform, new Vector2(0, 1), new Vector2(64, -52), new Vector2(150, 36)); logo.rectTransform.pivot = new Vector2(0, 1);

            var card = Card(root, 44, 16);
            card.anchorMin = card.anchorMax = card.pivot = new Vector2(0.5f, 0.5f); card.sizeDelta = new Vector2(600, 0); UI.Fit(card);
            UI.Text(card, "SIGN IN", TextStyle.Kicker, ColorRole.Ink);
            UI.Text(card, "Welcome " + UI.Em("back"), TextStyle.DisplayM, ColorRole.Ink);
            UI.Text(card, "Your rooms are waiting where you left them.", TextStyle.Body, ColorRole.InkMuted);
            var email = RField.Create(card, "Email", "you@email.com", initial: RoomLogic.Me.email);
            var pass = RField.Create(card, "Password", "Password", password: true, initial: "returnhome");
            RButton.Create(card, "Continue", BtnVariant.Primary, BtnSize.Lg, arrow: true, fullWidth: true, onClick: () =>
            {
                // Any input signs in, exactly like the web demo.
                app.store.SignIn(); app.router.ContinueAfterSignIn();
            });
        }
    }
}
