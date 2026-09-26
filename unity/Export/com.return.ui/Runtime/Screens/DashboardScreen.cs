using System;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    public class DashboardScreen : RoutedScreen
    {
        string _sig;
        float _scroll = 1f;

        public override void Build()
        {
            app.backdrop.Set(SceneKey.Painted);
            Rebuild();
        }

        public static (RoomStatus? status, string text, string meta) CardInfo(Room r)
        {
            int done = r.members.Count(m => m.status == MemberStatus.Done);
            var mine = RoomLogic.Mine(r);
            if (mine?.status == MemberStatus.Invited) return (RoomStatus.Invited, null, (r.invitedBy ?? "Someone") + " invited you");
            if (r.phase == Phase.Collecting && mine?.status != MemberStatus.Done) return (RoomStatus.New, "Add your photos", done + " of " + r.members.Count + " added photos");
            if (r.phase == Phase.Collecting) return (RoomStatus.Waiting, "Waiting for " + RoomLogic.WaitingOn(r), done + " of " + r.members.Count + " added photos");
            if (r.phase == Phase.Building) return (RoomStatus.Developing, null, r.members.Sum(m => m.count) + " photos");
            var meta = string.Join(" · ", new[] { r.place, r.date }.Where(s => !string.IsNullOrEmpty(s)));
            return (null, null, meta.Length > 0 ? meta : r.members.Count + " people");
        }

        static string Summary(System.Collections.Generic.List<Room> rooms)
        {
            var waiting = rooms.FirstOrDefault(r => r.phase == Phase.Collecting && RoomLogic.Mine(r)?.status == MemberStatus.Done);
            var building = rooms.FirstOrDefault(r => r.phase == Phase.Building);
            string note = waiting != null ? RoomLogic.WaitingOn(waiting) + " still " + (RoomLogic.Pending(waiting).Count > 1 ? "need" : "needs") + " to add photos to " + waiting.title
                : building != null ? building.title + " is coming into focus" : "Everything is ready to return to";
            return rooms.Count + " room" + (rooms.Count == 1 ? "" : "s") + " · " + note;
        }

        void Rebuild()
        {
            // keep scroll position across rebuilds
            var old = root.GetComponentInChildren<ScrollRect>(); if (old != null) _scroll = old.verticalNormalizedPosition;
            foreach (Transform c in root) if (c.name != "Sheet") UnityEngine.Object.Destroy(c.gameObject);
            var rooms = app.store.Rooms.ToList();
            _sig = Sig(rooms);
            var invites = rooms.Where(r => RoomLogic.Mine(r)?.status == MemberStatus.Invited).ToList();
            var yours = rooms.Where(r => RoomLogic.Mine(r)?.status != MemberStatus.Invited).ToList();

            var content = Scroll(112, new RectOffset(48, 48, 8, 60), 28);
            Nav("rooms");
            var hero = HeroFrame.Create(content, UIAssets.Sky(SceneKey.Painted), 250, "Welcome back, " + RoomLogic.Me.name.Split(' ')[0], "Your " + UI.Em("rooms"), Summary(yours));

            if (invites.Count > 0)
            {
                UI.Text(content, "Invitations", TextStyle.H1, ColorRole.OnImage);
                var g = Grid(content);
                foreach (var r in invites)
                {
                    var room = r; var (st, txt, meta) = CardInfo(r);
                    RoomCard.Create(g, RoomCard.CoverOf(r), r.title, meta, st, txt, null,
                        () => { app.store.Join(room.id); app.router.Go(Route.RoomUpload, room.id); },
                        null,
                        a =>
                        {
                            RButton.Create(a, "Join room", BtnVariant.Light, BtnSize.Sm, onClick: () => { app.store.Join(room.id); app.router.Go(Route.RoomUpload, room.id); });
                            RButton.Create(a, "Decline", BtnVariant.Glass, BtnSize.Sm, onClick: () => app.store.Decline(room.id));
                        });
                }
            }

            if (invites.Count > 0) UI.Text(content, "Your rooms", TextStyle.H1, ColorRole.OnImage);
            var grid = Grid(content);
            foreach (var r in yours)
            {
                var room = r; var (st, txt, meta) = CardInfo(r);
                RoomCard.Create(grid, RoomCard.CoverOf(r), r.title, meta, st, txt, People(r), () => app.router.OpenRoom(room), () => Manage(room));
            }
            NewTile(grid);
            LayoutRebuilder.ForceRebuildLayoutImmediate(content);
            var sr = root.GetComponentInChildren<ScrollRect>(); if (sr != null) sr.verticalNormalizedPosition = Mathf.Clamp01(_scroll);
        }

        static RectTransform Grid(Transform p)
        {
            var g = UI.Box(p, "Grid"); var gl = g.gameObject.AddComponent<GridLayoutGroup>();
            gl.cellSize = new Vector2(RoomCard.W, RoomCard.H); gl.spacing = new Vector2(24, 24); gl.constraint = GridLayoutGroup.Constraint.FixedColumnCount; gl.constraintCount = 3;
            gl.childAlignment = TextAnchor.UpperLeft; UI.Fit(g);
            return g;
        }

        void NewTile(Transform grid)
        {
            var t = UI.V(grid, "NewTile", 10, UI.Pad(28), TextAnchor.MiddleCenter);
            UI.Bg(t, ColorRole.GlassStrong, 32); UI.Border(t, ColorRole.LineStrong, 32, 2);
            var slot = UI.Fixed(t, "Dot", 64, 64);
            var dot = slot.gameObject.AddComponent<Image>(); dot.sprite = Shapes.Pill; dot.type = Image.Type.Sliced; UI.SetRole(dot, ColorRole.Action);
            UI.Icon(slot, "plus", ColorRole.OnAction, 28).rectTransform.anchoredPosition = Vector2.zero;
            UI.Text(t, "Create a " + UI.Em("room"), TextStyle.Title, ColorRole.Ink, TextAlignmentOptions.Center);
            UI.Text(t, "Pick a place, invite the people who were there.", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Center);
            var hit = UI.Img(t, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(hit.rectTransform); UI.Overlay(hit.rectTransform);
            var p = t.gameObject.AddComponent<Pressable>(); p.onClick = () => app.router.Go(Route.CreateRoom); p.hoverScale = 1.025f;
        }

        void Manage(Room r)
        {
            var owner = RoomLogic.IsMine(r);
            var sheet = Sheet.Show(root, 460);
            UI.Text(sheet.content, r.title, TextStyle.Title, ColorRole.Ink).fontSize = 30;
            if (owner) RButton.Create(sheet.content, "Rename", BtnVariant.Secondary, BtnSize.Md, fullWidth: true, onClick: () => { sheet.Close(); Rename(r); });
            RButton.Create(sheet.content, "Manage people", BtnVariant.Secondary, BtnSize.Md, "people", fullWidth: true, onClick: () => { sheet.Close(); People(r, null); });
            RButton.Create(sheet.content, owner ? "Delete room" : "Leave room", BtnVariant.Ghost, BtnSize.Md, fullWidth: true, onClick: () => { sheet.Close(); Remove(r); });
        }

        void Rename(Room r)
        {
            var s = Sheet.Show(root, 560);
            UI.Text(s.content, "Rename " + UI.Em("room"), TextStyle.Title, ColorRole.Ink).fontSize = 34;
            var f = RField.Create(s.content, "Room name", "Room name", initial: r.title);
            var row = Row(s.content, 12, 56, TextAnchor.MiddleRight);
            RButton.Create(row, "Cancel", BtnVariant.Ghost, onClick: s.Close);
            RButton.Create(row, "Save", BtnVariant.Primary, onClick: () => { if (!string.IsNullOrWhiteSpace(f.Text)) app.store.Rename(r.id, f.Text.Trim()); s.Close(); });
        }

        void People(Room r, object _)
        {
            var s = Sheet.Show(root, 640);
            var owner = RoomLogic.IsMine(r);
            var people = r.members.Select(m => new ShareSheet.Person2
            {
                name = m.name + (m.id == RoomLogic.MeId ? " (you)" : ""), isOwner = m.isOwner,
                note = m.status == MemberStatus.Done ? "Added " + m.count + " photos" : m.status == MemberStatus.Joined ? "Joined" : "Invited",
                onRemove = owner && !m.isOwner ? (Action)(() => { app.store.Uninvite(r.id, m.id); s.Close(); People(app.store.Get(r.id), null); }) : null,
            }).ToList();
            ShareSheet.Build(s.content, r.title, people, v => { app.store.Invite(r.id, v); s.Close(); People(app.store.Get(r.id), null); }, s.Close);
        }

        void Remove(Room r)
        {
            var owner = RoomLogic.IsMine(r);
            var s = Sheet.Show(root, 560);
            UI.Text(s.content, (owner ? "Delete " : "Leave ") + UI.Em(r.title), TextStyle.Title, ColorRole.Ink).fontSize = 34;
            UI.Text(s.content, owner ? "This removes the room for everyone in it, and it disappears from their headsets." : "You won't see this room anymore. The others keep it.", TextStyle.Body, ColorRole.InkMuted);
            var row = Row(s.content, 12, 56, TextAnchor.MiddleRight);
            RButton.Create(row, "Keep it", BtnVariant.Ghost, onClick: s.Close);
            RButton.Create(row, owner ? "Delete room" : "Leave room", BtnVariant.Danger, onClick: () => { s.Close(); if (owner) app.store.Remove(r.id); else app.store.Leave(r.id); });
        }

        public override void OnStoreChanged()
        {
            if (root == null) return;
            if (Sig(app.store.Rooms) != _sig && root.GetComponentInChildren<Sheet>() == null) Rebuild();
        }
    }
}
