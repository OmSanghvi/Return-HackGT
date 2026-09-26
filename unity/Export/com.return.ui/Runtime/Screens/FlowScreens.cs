using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Step 1 of 3: name it and invite people.</summary>
    public class CreateRoomScreen : RoutedScreen
    {
        readonly List<Person> _invited = new List<Person>();
        RField _name; TextMeshProUGUI _note;

        public override void Build()
        {
            app.backdrop.Set(SceneKey.Home);
            var scrim = UI.Img(root, "Scrim", ColorRole.ImageScrim, Shapes.GradientUp); scrim.rectTransform.localScale = new Vector3(1, -1, 1); UI.Stretch(scrim.rectTransform); scrim.color = new Color(0, 0, 0, 0);
            scrim.GetComponent<ThemedGraphic>().enabled = false;

            var content = Scroll(112, new RectOffset(48, 48, 8, 60), 20);
            var split = UI.H(content, "Split", 28, null, TextAnchor.UpperLeft); var sg = split.GetComponent<HorizontalLayoutGroup>(); sg.childForceExpandWidth = false; sg.childForceExpandHeight = false; sg.childControlHeight = true;

            var form = Card(split, 40, 18); UI.Size(form, 760);
            Stepper.Create(form, 0);
            UI.Text(form, "Start a new " + UI.Em("room"), TextStyle.DisplayL, ColorRole.Ink);
            UI.Text(form, "One place, one moment. Everyone you invite adds their own photos of it.", TextStyle.BodyL, ColorRole.InkMuted);
            _name = RField.Create(form, "Name this room", "The lake house, summer 2019", "Shown on the room's card and in the headset.");
            _name.input.onValueChanged.AddListener(_ => _name.SetError(null));
            InviteSearch.Create(form, _invited, UpdateNote);
            var actions = Row(form, 12, 64);
            RButton.Create(actions, "Next: add your photos", BtnVariant.Primary, BtnSize.Lg, arrow: true, onClick: () => Create(true));
            RButton.Create(actions, "Invite people later", BtnVariant.Ghost, BtnSize.Lg, onClick: () => Create(false));

            var side = Card(split, 36, 8); UI.Size(side, 400);
            UI.Text(side, "Better " + UI.Em("together"), TextStyle.Title, ColorRole.Ink).fontSize = 34;
            _note = UI.Text(side, "", TextStyle.Body, ColorRole.InkMuted);
            UpdateNote();

            var nav = Nav(null, false);
            var cancel = UI.Box(nav, "Cancel"); // sits on the right of the nav wrap
            cancel.anchorMin = cancel.anchorMax = new Vector2(1, 0.5f); cancel.pivot = new Vector2(1, 0.5f); cancel.anchoredPosition = new Vector2(-190, 0); cancel.sizeDelta = new Vector2(160, 56);
            var cb = RButton.Create(cancel, "Cancel", BtnVariant.Ghost, BtnSize.Md, "x", onClick: () => app.router.Go(Route.Dashboard)); UI.Stretch((RectTransform)cb.transform);
        }

        void UpdateNote()
        {
            if (_note == null) return;
            _note.text = "Each person remembers the place from a different spot. " + (_invited.Count > 0
                ? "With " + (_invited.Count + 1) + " of you, return can rebuild more of the room." : "More angles let return rebuild more of the room.");
        }

        void Create(bool withInvites)
        {
            if (string.IsNullOrWhiteSpace(_name.Text)) { _name.SetError("Give the room a name, like the place or the day."); return; }
            var id = app.store.CreateRoom(_name.Text, withInvites ? _invited.Select(p => p.email) : Enumerable.Empty<string>());
            app.router.Go(Route.RoomUpload, id);
        }
    }

    /// <summary>Step 2 of 3: add your view of it.</summary>
    public class RoomUploadScreen : RoutedScreen
    {
        readonly List<string> _photos = new List<string>();
        RField _note, _objects; RButton _submit; RectTransform _objectsHolder;
        string _sig;

        public static MemberRow[] Rows(Room r, long now) => r.members.Select(m => new MemberRow
        {
            name = m.name, email = m.email, count = m.count, hasNote = !string.IsNullOrEmpty(m.note), isOwner = m.isOwner, isYou = m.id == RoomLogic.MeId,
            status = m.status, sentAgo = RoomLogic.AgoText(m.invitedAt, now),
        }).ToArray();

        public override void Build()
        {
            var room = Room; if (room == null) return;
            app.backdrop.Set(room.scene);
            if (RoomLogic.Mine(room)?.status == MemberStatus.Invited) app.store.Join(room.id);

            var content = Scroll(112, new RectOffset(48, 48, 8, 60), 20);
            var split = UI.H(content, "Split", 28, null, TextAnchor.UpperLeft); var sg = split.GetComponent<HorizontalLayoutGroup>(); sg.childForceExpandWidth = false; sg.childForceExpandHeight = false; sg.childControlHeight = true;

            var form = Card(split, 40, 18); UI.Size(form, 760);
            var crumb = UI.Text(form, "Rooms / " + room.title, TextStyle.Caption, ColorRole.InkMuted);
            Stepper.Create(form, 1);
            UI.Text(form, "Add your " + UI.Em("view") + " of it", TextStyle.DisplayL, ColorRole.Ink);
            var drop = PhotoDrop.Create(form, _photos, 12, OnPhotos);
            _objectsHolder = UI.V(form, "ObjectsHolder", 0);
            _note = RField.Create(form, "Leave a note for this room", "What do you remember about being here?", "Everyone in the room can read it, and it floats beside your photos in the headset.", multiline: true, maxLength: 1000);
            var actions = Row(form, 12, 64);
            _submit = RButton.Create(actions, "Add to the room", BtnVariant.Primary, BtnSize.Lg, arrow: true, onClick: Submit);
            RButton.Create(actions, "Save for later", BtnVariant.Ghost, BtnSize.Lg, onClick: () => app.router.Go(Route.Dashboard));

            var side = Card(split, 32, 14); UI.Size(side, 400);
            UI.Text(side, "In this " + UI.Em("room"), TextStyle.Title, ColorRole.Ink).fontSize = 32;
            MemberList.Create(side, Rows(room, Now()), m =>
            {
                var x = room.members.FirstOrDefault(y => y.email == m.email); if (x != null) app.store.Resend(room.id, x.id);
            });
            var inv = RField.Create(side, "Invite someone else", "their@email.com", submitLabel: "Invite");
            inv.Submitted += v => { if (InviteSearch.IsEmail(v.Trim())) { app.store.Invite(room.id, v.Trim()); inv.Clear(); } };
            _sig = Sig(app.store.Rooms);
            Nav(null);
        }

        static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        void OnPhotos()
        {
            app.backdrop.SetMist(_photos.Count > 0 ? 0f : 0.35f);
            // owner may say what to rebuild once there are photos
            foreach (Transform c in _objectsHolder) UnityEngine.Object.Destroy(c.gameObject);
            if (RoomLogic.IsMine(Room) && _photos.Count > 0)
                _objects = RField.Create(_objectsHolder, "What should we rebuild? (optional)", "Everything",
                    "Leave blank and we rebuild everything in your photos. For a wide shot, list the things you care about, like: the porch swing, the blue vase.", maxLength: 400, initial: _objects != null ? _objects.Text : string.Join(", ", Room.objects));
        }

        void Submit()
        {
            if (_photos.Count == 0) { _note.SetError("Add at least one photo of the place first."); return; }
            var room = Room; if (room == null) return;
            _submit.SetLoading(true); _submit.SetText("Adding");
            // A beat for the upload to feel real, then on to waiting.
            app.router.StartCoroutine(Done(room));
        }

        IEnumerator Done(Room room)
        {
            yield return new WaitForSecondsRealtime(0.9f);
            app.store.AddPhotos(room.id, _photos, _note.Text, RoomLogic.IsMine(room) && _objects != null ? RoomLogic.ParseObjects(_objects.Text) : null);
            app.router.Go(Route.Room, room.id);
        }
    }

    /// <summary>Step 3 of 3: waiting, building, and ready.</summary>
    public class RoomScreen : RoutedScreen
    {
        Phase _phase; string _sig; DevelopProgress.Handle _dev; bool _built; RectTransform _bodyHolder;

        public override void Build()
        {
            var room = Room; if (room == null) return;
            Rebuild(room);
        }

        void Rebuild(Room room)
        {
            foreach (Transform c in root) UnityEngine.Object.Destroy(c.gameObject);
            _phase = room.phase; _sig = RoomSig(room); _dev = null;
            ThemeManager.SetForced(room.phase == Phase.Ready ? ReturnTheme.Dusk : (ReturnTheme?)null);
            if (room.phase == Phase.Ready) BuildReady(room); else BuildWaiting(room);
            Nav();
        }

        static string RoomSig(Room r) => r.phase + "|" + r.title + "|" + string.Join(",", r.members.Select(m => m.id + m.status + m.count));

        public override void OnExit() { ThemeManager.SetForced(null); app.backdrop.SetMist(0); }

        void BuildWaiting(Room room)
        {
            bool building = room.phase == Phase.Building;
            app.backdrop.Set(building ? room.scene : SceneKey.Plain);
            app.backdrop.SetMist(building ? Mathf.Max(0, 1f - room.progress * 1.1f) : 0f);

            var holder = UI.Box(root, "Holder"); UI.Stretch(holder, 0, 0, 0, 112);
            var card = Card(holder, 40, 18); card.anchorMin = card.anchorMax = card.pivot = new Vector2(0.5f, 0.5f); card.sizeDelta = new Vector2(1000, 0); UI.Fit(card);
            Stepper.Create(card, 2);
            if (building)
            {
                _dev = DevelopProgress.Create(card, RoomCard.CoverOf(room), room.title, room.progress, a => RButton.Create(a, "Back to rooms", BtnVariant.Ghost, BtnSize.Md, "back", onClick: () => app.router.Go(Route.Dashboard)));
                return;
            }
            int done = room.members.Count(m => m.status == MemberStatus.Done);
            var who = RoomLogic.WaitingOn(room);
            var others = RoomLogic.Pending(room).Where(m => m.id != RoomLogic.MeId).ToList();
            UI.Text(card, "Waiting for " + who, TextStyle.DisplayM, ColorRole.Ink);
            UI.Text(card, done + " of " + room.members.Count + " have added their photos. We start building the moment everyone is in, and email you when the room is ready.", TextStyle.Body, ColorRole.InkMuted);
            var bar = Bar.Create(card, ColorRole.Sun, 10); bar.Set(room.members.Count == 0 ? 0 : (float)done / room.members.Count);
            MemberList.Create(card, RoomUploadScreen.Rows(room, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), m => { var x = room.members.FirstOrDefault(y => y.email == m.email); if (x != null) app.store.Resend(room.id, x.id); });
            var row = Row(card, 12, 56, TextAnchor.MiddleLeft);
            RButton.Create(row, "Back to rooms", BtnVariant.Text, BtnSize.Md, "back", onClick: () => app.router.Go(Route.Dashboard));
            UI.Spacer(row, 0, 0, true);
            if (RoomLogic.IsMine(room) && others.Count > 0)
                ConfirmButton.Create(row, "Start without " + who, "Build with " + done + " " + (done == 1 ? "person" : "people") + "'s photos?", () => app.store.StartBuilding(room.id));
        }

        void BuildReady(Room room)
        {
            app.backdrop.Set(SceneKey.Night); app.backdrop.SetMist(0);
            int photos = room.members.Sum(m => m.count);
            var scrim = UI.Img(root, "Scrim", ColorRole.ImageScrimStrong, Shapes.GradientUp); scrim.rectTransform.localScale = new Vector3(1, -1, 1); UI.Stretch(scrim.rectTransform, -420, -260, -420, 120);

            var body = UI.V(root, "Copy", 14, new RectOffset(72, 0, 0, 72), TextAnchor.LowerLeft); UI.Stretch(body); body.offsetMax = new Vector2(-560, 0);
            Eyebrow.Create(body, "Ready", "Built from " + photos + " photos by " + room.members.Count + " " + (room.members.Count == 1 ? "person" : "people"));
            UI.Text(body, room.title + " is " + UI.Em("ready"), TextStyle.Hero, ColorRole.OnImage);
            UI.Text(body, "It's waiting in your headset now. Everyone who added photos can step in, together or on their own.", TextStyle.BodyL, ColorRole.OnImage);
            PresenceStack.Create(body, room.members.Select(m => new Who(m.name)).ToArray(), 4, 56, false, true);
            UI.Spacer(body, 0, 6);
            var actions = Row(body, 12, 64);
            if (app.router.ctx.enterWorld != null) RButton.Create(actions, "Step inside", BtnVariant.Light, BtnSize.Lg, "enter", arrow: true, onClick: () => app.router.ctx.enterWorld(room));
            RButton.Create(actions, "Back to rooms", BtnVariant.Glass, BtnSize.Lg, "back", onClick: () => app.router.Go(Route.Dashboard));

            var side = UI.V(root, "Side", 20, null, TextAnchor.MiddleCenter); side.anchorMin = new Vector2(1, 0); side.anchorMax = new Vector2(1, 1); side.pivot = new Vector2(1, 0.5f); side.sizeDelta = new Vector2(500, 0); side.anchoredPosition = new Vector2(-48, -30);
            var g = side.GetComponent<VerticalLayoutGroup>(); g.childForceExpandWidth = false; g.childAlignment = TextAnchor.MiddleCenter;
            var portal = PortalWindow.Create(side, RoomCard.CoverOf(room), 300, 400, null);
            var hint = UI.H(side, "Hint", 8, null, TextAnchor.MiddleCenter); var hg = hint.GetComponent<HorizontalLayoutGroup>(); hg.childForceExpandWidth = false;UI.Size(hint, 460, 28);
            UI.Icon(hint, "headset", ColorRole.OnImage, 20); UI.Text(hint, "Put on your headset to step inside", TextStyle.Caption, ColorRole.OnImage, TextAlignmentOptions.Left, false);
            var help = Card(side, 26, 10, 28); UI.Size(help, 460);
            UI.Text(help, "On your " + UI.Em("headset"), TextStyle.Title, ColorRole.Ink).fontSize = 28;
            var s1 = Row(help, 10, 30); UI.Icon(s1, "headset", ColorRole.Ink, 20); UI.Text(s1, "Open return on your Quest", TextStyle.Body, ColorRole.Ink, TextAlignmentOptions.Left, false);
            var s2 = Row(help, 10, 30); UI.Icon(s2, "lock", ColorRole.Ink, 20); UI.Text(s2, "Sign in with this same account", TextStyle.Body, ColorRole.Ink, TextAlignmentOptions.Left, false);
        }

        public override void OnStoreChanged()
        {
            if (root == null) return;
            var room = Room;
            if (room == null) { app.router.Go(Route.Dashboard); return; }
            if (RoomSig(room) != _sig && root.GetComponentInChildren<Sheet>() == null)
            {
                if (room.phase == Phase.Collecting && RoomLogic.Mine(room)?.status != MemberStatus.Done) { app.router.Go(Route.RoomUpload, room.id); return; }
                Rebuild(room); return;
            }
            if (room.phase == Phase.Building && _dev != null)
            {
                _dev.Set(room.progress);
                app.backdrop.SetMist(Mathf.Max(0, 1f - room.progress * 1.1f));
            }
        }
    }
}
