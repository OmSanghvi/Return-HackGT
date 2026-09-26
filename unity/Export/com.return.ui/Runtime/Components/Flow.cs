using System;
using System.Collections.Generic;
using System.Linq;
using Return.Data;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Stub picker: there is no native file picker on Quest, so "choose photos" hands back sample images. Swap for a real picker.</summary>
    public static class PhotoLibrary
    {
        // ponytail: sample photos are the painted skies. Replace Pick with a native/Android gallery picker when the headset build lands.
        public static readonly string[] Samples = { "Home", "Meadow", "Beach", "Plain", "Clouds", "Painted", "CloudSea", "Night" };

        public static List<string> Pick(ICollection<string> already, int count, int max)
        {
            var res = new List<string>();
            foreach (var s in Samples)
            {
                if (res.Count >= count || already.Count + res.Count >= max) break;
                if (!already.Contains(s)) res.Add(s);
            }
            return res;
        }
    }

    public static class DevelopProgress
    {
        public static readonly string[] Steps = { "Reading your photos", "Estimating depth", "Building the world", "Setting the light" };

        public class Handle { public Action<float> Set; }

        /// <summary>The build screen: the cover coming out of fog beside a progress bar and four labelled steps. Steps are labels only, no model runs.</summary>
        public static Handle Create(Transform parent, Texture cover, string title, float progress, Action<Transform> actions = null)
        {
            var row = UI.H(parent, "DevelopProgress", 32, null, TextAnchor.UpperLeft);
            var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;
            UI.Size(row, -1, 300);

            var frame = UI.Box(row, "Photo", 300, 300); Clip.Rounded(frame, 28);
            var photo = UI.Photo(frame, "Cover", cover); UI.Stretch(photo.rectTransform);
            var mist = UI.Img(frame, "Mist", ColorRole.Canvas, Shapes.White); UI.Stretch(mist.rectTransform);

            var col = UI.V(row, "Col", 12); UI.Size(col, -1, -1, 1);
            var head = UI.Text(col, "", TextStyle.DisplayM, ColorRole.Ink); head.fontSize = 40;
            var sub = UI.Text(col, "", TextStyle.Body, ColorRole.InkMuted);
            var bar = Bar.Create(col, ColorRole.Sun, 10);
            var stepRows = new List<(Image icon, TextMeshProUGUI label)>();
            var list = UI.V(col, "Steps", 8);
            foreach (var s in Steps)
            {
                var r = UI.H(list, "Step", 10, null, TextAnchor.MiddleLeft); var rg = r.GetComponent<HorizontalLayoutGroup>(); rg.childForceExpandWidth = false;UI.Size(r, -1, 28);
                var ic = UI.Icon(r, "clock", ColorRole.InkFaint, 18);
                var lb = UI.Text(r, s, TextStyle.Body, ColorRole.InkFaint, TextAlignmentOptions.Left, false);
                stepRows.Add((ic, lb));
            }
            if (actions != null) { var a = UI.H(col, "Actions", 12, UI.Pad(0, 6)); var ag = a.GetComponent<HorizontalLayoutGroup>(); ag.childForceExpandWidth = false;UI.Size(a, -1, 64); actions(a); }

            int lastCur = -2;
            void Set(float p)
            {
                p = Mathf.Clamp01(p);
                int cur = Mathf.Min(Steps.Length - 1, Mathf.FloorToInt(p * Steps.Length));
                bool done = p >= 1f;
                // fog lifts: brighter and washed out at 0, true color at 1 (the web blurs; a flat tint is the cheap VR-safe stand-in)
                photo.color = Color.Lerp(new Color(0.55f, 0.58f, 0.66f), Color.white, p);
                var mc = mist.color; mist.GetComponent<ThemedGraphic>().enabled = false; mist.color = new Color(mc.r, mc.g, mc.b, (1f - p) * 0.75f);
                bar.Set(p, done ? ColorRole.Success : ColorRole.Sun);
                if (cur == lastCur && !done) return;
                lastCur = cur;
                head.text = done ? "Ready to " + UI.Em("return") : "Coming into " + UI.Em("focus");
                sub.text = done ? "Put on your headset. It's waiting in your rooms." : (string.IsNullOrEmpty(title) ? "" : title + " · ") + "About a minute. You can leave this page.";
                for (int i = 0; i < stepRows.Count; i++)
                {
                    var state = i < cur || done ? 0 : i == cur ? 1 : 2;
                    var role = state == 0 ? ColorRole.Success : state == 1 ? ColorRole.Ink : ColorRole.InkFaint;
                    stepRows[i].icon.sprite = UIAssets.Icon(state == 0 ? "check" : state == 1 ? "spinner" : "clock");
                    UI.SetRole(stepRows[i].icon, role); UI.SetRole(stepRows[i].label, role);
                    var sp = stepRows[i].icon.GetComponent<Spin>();
                    if (state == 1 && sp == null) stepRows[i].icon.gameObject.AddComponent<Spin>();
                    if (state != 1 && sp != null) { UnityEngine.Object.Destroy(sp); stepRows[i].icon.transform.localRotation = Quaternion.identity; }
                }
            }
            Set(progress);
            return new Handle { Set = Set };
        }
    }

    public static class PhotoDrop
    {
        public class Handle { public Action Refresh; }

        /// <summary>Drop zone plus a strip of thumbnails. In VR the zone is a big "Choose photos" target. photos is edited in place.</summary>
        public static Handle Create(Transform parent, List<string> photos, int max, Action onChanged)
        {
            var root = UI.V(parent, "PhotoDrop", 16);
            var handle = new Handle();
            RectTransform zoneHolder = UI.V(root, "Zone", 0);
            RectTransform stripHolder = UI.V(root, "Strip", 10);

            void Rebuild()
            {
                foreach (Transform c in zoneHolder) UnityEngine.Object.Destroy(c.gameObject);
                foreach (Transform c in stripHolder) UnityEngine.Object.Destroy(c.gameObject);
                var zone = UI.V(zoneHolder, "Drop", 8, UI.Pad(32, 28), TextAnchor.MiddleCenter);
                UI.Size(zone, -1, 190);
                UI.Bg(zone, ColorRole.GlassStrong, 28); UI.Border(zone, ColorRole.LineStrong, 28, 2);
                var slot = UI.Fixed(zone, "IconWrap", 56, 56);
                var ic = slot.gameObject.AddComponent<Image>(); ic.sprite = Shapes.Pill; ic.type = Image.Type.Sliced; UI.SetRole(ic, ColorRole.SkySoft);
                UI.Icon(slot, "upload", ColorRole.Sky, 28).rectTransform.anchoredPosition = Vector2.zero;
                var t = UI.Text(zone, "Bring a " + UI.Em("moment") + " back", TextStyle.Title, ColorRole.Ink, TextAlignmentOptions.Center); t.fontSize = 32;
                UI.Text(zone, "Choose 1 to " + max + " photos of the same place. More angles build a fuller world.", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Center);
                var hit = UI.Img(zone, "Hit", ColorRole.Ink, null, Image.Type.Simple, true); hit.color = new Color(0, 0, 0, 0); hit.GetComponent<ThemedGraphic>().enabled = false; UI.Stretch(hit.rectTransform); UI.Overlay(hit.rectTransform);
                var p = zone.gameObject.AddComponent<Pressable>(); p.hoverScale = 1.01f;
                p.onClick = () => { var add = PhotoLibrary.Pick(photos, 3, max); if (add.Count == 0) return; photos.AddRange(add); Rebuild(); onChanged?.Invoke(); };

                if (photos.Count == 0) return;
                var strip = UI.H(stripHolder, "Thumbs", 10, UI.Pad(0, 4)); var sg = strip.GetComponent<HorizontalLayoutGroup>(); sg.childForceExpandWidth = false;UI.Size(strip, -1, 108);
                for (int i = 0; i < photos.Count; i++)
                {
                    int idx = i;
                    var th = UI.Box(strip, "Thumb", 100, 100); UI.Size(th, 100, 100); Clip.Rounded(th, 18);
                    var ph = UI.Photo(th, "Photo", UIAssets.Photo(photos[i])); UI.Stretch(ph.rectTransform);
                    var x = UI.Img(th, "Remove", ColorRole.ImageScrimStrong, Shapes.Pill, Image.Type.Sliced, true);
                    UI.Anchor(x.rectTransform, new Vector2(1, 1), new Vector2(-6, -6), new Vector2(34, 34)); x.rectTransform.pivot = new Vector2(1, 1);
                    UI.Icon(x.rectTransform, "x", ColorRole.OnImage, 16).rectTransform.anchoredPosition = Vector2.zero;
                    x.gameObject.AddComponent<Pressable>().onClick = () => { photos.RemoveAt(idx); Rebuild(); onChanged?.Invoke(); };
                    if (i == 0) UI.Border(th, ColorRole.Sky, 18, 3);
                }
                var meta = UI.H(stripHolder, "Meta", 0); var mg = meta.GetComponent<HorizontalLayoutGroup>(); mg.childForceExpandWidth = false;UI.Size(meta, -1, 24);
                UI.Text(meta, photos.Count + " of " + max + " photos", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Left, false);
                UI.Spacer(meta, 0, 0, true);
                UI.Text(meta, "The first photo is the cover", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Right, false);
            }
            handle.Refresh = Rebuild;
            Rebuild();
            return handle;
        }
    }

    public static class InviteSearch
    {
        static readonly System.Text.RegularExpressions.Regex Email = new System.Text.RegularExpressions.Regex(@"^[^\s@]+@[^\s@]+\.[^\s@]+$");
        public static bool IsEmail(string s) => Email.IsMatch(s ?? "");

        public class Handle { public Action Refresh; }

        /// <summary>Search the known-people directory by name or email prefix; a typed full email offers an invite.</summary>
        public static Handle Create(Transform parent, List<Person> invited, Action onChanged, string label = "Invite people by email")
        {
            var root = UI.V(parent, "InviteSearch", 12);
            var field = RField.Create(root, label, "Search by name or email");
            var results = UI.V(root, "Results", 4);
            var chipsHolder = UI.V(root, "Chips", 8);
            var h = new Handle();

            IEnumerable<Person> Match(string q)
            {
                q = q.Trim().ToLowerInvariant(); if (q.Length == 0) return Enumerable.Empty<Person>();
                bool Starts(Person p) => (p.name.ToLowerInvariant().Split(' ').Concat(new[] { p.email })).Any(w => w.StartsWith(q));
                return RoomLogic.KnownPeople.Where(p => (p.name + " " + p.email).ToLowerInvariant().Contains(q)).OrderByDescending(Starts).Take(4);
            }

            bool IsInvited(string email) => invited.Any(p => p.email == email);

            void Invite(Person p) { if (!IsInvited(p.email)) invited.Add(p); field.Clear(); Rebuild(); onChanged?.Invoke(); }

            void Rebuild()
            {
                foreach (Transform c in results) UnityEngine.Object.Destroy(c.gameObject);
                foreach (Transform c in chipsHolder) UnityEngine.Object.Destroy(c.gameObject);
                var q = field.Text.Trim();
                var found = Match(q).ToList();
                bool raw = IsEmail(q) && !found.Any(f => f.email == q) && !IsInvited(q);
                if (q.Length > 0 && found.Count == 0 && !raw) UI.Text(results, "No one found. Type their full email to invite them.", TextStyle.Caption, ColorRole.InkMuted);
                foreach (var p in found) ResultRow(p, false);
                if (raw) ResultRow(new Person { email = q, name = null }, true);

                if (invited.Count > 0)
                {
                    UI.Text(chipsHolder, "Invited (" + invited.Count + ")", TextStyle.Overline, ColorRole.InkMuted);
                    var wrap = UI.Box(chipsHolder, "Wrap"); var grid = wrap.gameObject.AddComponent<GridLayoutGroup>();
                    grid.cellSize = new Vector2(280, 48); grid.spacing = new Vector2(10, 10); grid.constraint = GridLayoutGroup.Constraint.FixedColumnCount; grid.constraintCount = 2;
                    UI.Fit(wrap);
                    foreach (var p in invited.ToList())
                    {
                        var chip = UI.H(wrap, "Chip", 8, new RectOffset(8, 6, 0, 0), TextAnchor.MiddleLeft);
                        var cg = chip.GetComponent<HorizontalLayoutGroup>(); cg.childForceExpandWidth = false;
                        UI.Bg(chip, ColorRole.Surface300, 48);
                        Avatars.Create(chip, p.name ?? p.email, 32);
                        var tx = UI.Text(chip, p.name ?? p.email, TextStyle.Caption, ColorRole.Ink, TextAlignmentOptions.Left, false); tx.overflowMode = TextOverflowModes.Ellipsis; UI.Size(tx.rectTransform, -1, -1, 1);
                        var x = UI.Img(chip, "X", ColorRole.Surface300, Shapes.Pill, Image.Type.Sliced, true); UI.Size(x.rectTransform, 36, 36); x.rectTransform.sizeDelta = new Vector2(36, 36);
                        UI.Icon(x.rectTransform, "x", ColorRole.InkMuted, 14).rectTransform.anchoredPosition = Vector2.zero;
                        var pp = p; x.gameObject.AddComponent<Pressable>().onClick = () => { invited.Remove(pp); Rebuild(); onChanged?.Invoke(); };
                    }
                }
            }

            void ResultRow(Person p, bool isNew)
            {
                var row = UI.H(results, "Result", 12, new RectOffset(10, 10, 6, 6), TextAnchor.MiddleLeft);
                var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(row, -1, 68);
                UI.Bg(row, ColorRole.Surface200, 20);
                if (isNew) { var a = UI.Img(row, "Mail", ColorRole.AuroraSoft, Shapes.Pill, Image.Type.Sliced); UI.Size(a.rectTransform, 44, 44); a.rectTransform.sizeDelta = new Vector2(44, 44); UI.Icon(a.rectTransform, "mail", ColorRole.Aurora, 20).rectTransform.anchoredPosition = Vector2.zero; }
                else Avatars.Create(row, p.name, 44);
                var col = UI.V(row, "Col", 0, null, TextAnchor.MiddleLeft); UI.Size(col, -1, -1, 1);
                UI.Text(col, isNew ? "Invite " + p.email : p.name, TextStyle.Label, ColorRole.Ink, TextAlignmentOptions.Left, false);
                UI.Text(col, isNew ? "Not on return yet. We'll email them an invite." : p.email, TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Left, false);
                if (IsInvited(p.email)) { var d = UI.H(row, "Done", 6); UI.Icon(d, "check", ColorRole.Success, 16); UI.Text(d, "Invited", TextStyle.Caption, ColorRole.Success, TextAlignmentOptions.Left, false); }
                else RButton.Create(row, "Invite", BtnVariant.Secondary, BtnSize.Sm, "plus", onClick: () => Invite(p));
            }

            field.input.onValueChanged.AddListener(_ => Rebuild());
            field.Submitted += v => { var q = v.Trim(); if (IsEmail(q)) Invite(new Person { email = q, name = RoomLogic.NameFor(q) }); };
            h.Refresh = Rebuild;
            Rebuild();
            return h;
        }
    }

    public static class ShareSheet
    {
        public class Person2 { public string name, note; public bool isOwner; public Action onRemove; }

        public static void Build(RectTransform card, string title, List<Person2> people, Action<string> onInvite, Action onClose)
        {
            var head = UI.H(card, "Head", 12, null, TextAnchor.UpperLeft); var hg = head.GetComponent<HorizontalLayoutGroup>(); hg.childForceExpandWidth = false; hg.childControlHeight = true; hg.childForceExpandHeight = false;
            var col = UI.V(head, "Col", 4); UI.Size(col, -1, -1, 1);
            var t = UI.Text(col, "Who can " + UI.Em("return") + " here", TextStyle.Title, ColorRole.Ink); t.fontSize = 34;
            if (!string.IsNullOrEmpty(title)) UI.Text(col, title, TextStyle.Caption, ColorRole.InkMuted);
            if (onClose != null)
            {
                var x = UI.Img(head, "Close", ColorRole.Surface300, Shapes.Pill, Image.Type.Sliced, true); UI.Size(x.rectTransform, 48, 48); x.rectTransform.sizeDelta = new Vector2(48, 48);
                UI.Icon(x.rectTransform, "x", ColorRole.Ink, 20).rectTransform.anchoredPosition = Vector2.zero;
                x.gameObject.AddComponent<Pressable>().onClick = onClose;
            }
            var f = RField.Create(card, "Invite by email", "sam@school.edu", submitLabel: "Invite");
            f.Submitted += v => { if (!string.IsNullOrWhiteSpace(v)) { onInvite?.Invoke(v.Trim()); f.Clear(); } };
            if (people.Count == 0) return;
            UI.Text(card, "People with access", TextStyle.Overline, ColorRole.InkMuted);
            foreach (var p in people)
            {
                var row = UI.H(card, "Person", 12, new RectOffset(4, 4, 6, 6), TextAnchor.MiddleLeft); var g = row.GetComponent<HorizontalLayoutGroup>(); g.childForceExpandWidth = false;UI.Size(row, -1, 64);
                Avatars.Create(row, p.name, 44);
                var c = UI.V(row, "Col", 0, null, TextAnchor.MiddleLeft); UI.Size(c, -1, -1, 1);
                UI.Text(c, p.name, TextStyle.Label, ColorRole.Ink, TextAlignmentOptions.Left, false);
                UI.Text(c, p.isOwner ? "Made this room" : p.note ?? "Invited", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Left, false);
                if (p.isOwner) UI.Text(row, "Owner", TextStyle.Caption, ColorRole.InkMuted, TextAlignmentOptions.Right, false);
                else if (p.onRemove != null) RButton.Create(row, "Remove", BtnVariant.Ghost, BtnSize.Sm, onClick: p.onRemove);
            }
        }
    }
}
