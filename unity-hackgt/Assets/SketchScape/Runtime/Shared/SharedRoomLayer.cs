// SketchScape SharedRoomLayer — draws the shared view in the room (WEB_TO_QUEST_PIPELINE.md section 5).
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
//  - Personal notes: a paper card on a little stand beside the author's reconstructed object
//    (note.asset_ids -> room object via the map RoomKit baked), else pinned on a notes board by
//    the spawn. Header band in the author's colour with the author's label.
//  - Letters: one envelope per letter on the letters desk by the spawn; "For Account N"; a soft
//    glow when this viewer may open it; poke/ray it to open (session.OpenLetter), which unfolds
//    the page (SharedLetterPage) with the letter's texture or body text.
//  - Attribution: a small tent card on each object with its label and contributor colour.
// Redrawn on every view change (account switch, re-read); nothing runs per frame here.
using System.Collections.Generic;
using TMPro;
using UnityEngine;

namespace SketchScape
{
    [DisallowMultipleComponent]
    public class SharedRoomLayer : MonoBehaviour
    {
        public const string ContentName = "Shared Content";
        public const string TagName = "Shared Tag";

        public SharedRoomSession session;
        [Header("Anchors (set by RoomKit; +Z points away from the spawn)")]
        public Transform deskAnchor;
        public Transform boardAnchor;
        public SharedLetterPage page;
        [Tooltip("Player spawn on the floor (world).")]
        public Vector3 spawn;
        public float eyeHeight = 1.6f;
        public float floorY = 0f;

        [Header("Room objects (asset_id -> object), baked by RoomKit")]
        public string[] mapAssetIds = new string[0];
        public string[] mapObjectIds = new string[0];
        public Transform[] mapObjects = new Transform[0];

        public SharedLayerLook look = new SharedLayerLook();

        /// <summary>What the last redraw produced, e.g. "notes 2 (objects 2, board 0), letters 2, tags 6".</summary>
        public string LastRender { get; private set; }

        Transform _content;
        readonly List<SharedEnvelope> _envelopes = new List<SharedEnvelope>();
        readonly List<GameObject> _tags = new List<GameObject>();

        const float DeskTop = 0.78f;

        void OnEnable()
        {
            look.EnsureDefaults();
            if (session == null) session = GetComponent<SharedRoomSession>();
            if (session == null) return;
            session.ViewChanged += Render;
            session.LetterOpened += OnLetterOpened;
            session.LetterRefused += OnLetterRefused;
            if (session.View != null) Render(session.View);
        }

        void OnDisable()
        {
            if (session == null) return;
            session.ViewChanged -= Render;
            session.LetterOpened -= OnLetterOpened;
            session.LetterRefused -= OnLetterRefused;
        }

        void OnDestroy()
        {
            if (Application.isPlaying) look.Release();
        }

        // ------------------------------------------------------------------
        // Furniture (baked once by RoomKit)
        // ------------------------------------------------------------------

        /// <summary>Letters desk with the page stand. Called by RoomKit when it bakes the room.</summary>
        public void BuildFurniture()
        {
            look.EnsureDefaults();
            if (deskAnchor == null) return;
            for (int i = deskAnchor.childCount - 1; i >= 0; i--) SharedShapes.Destroy(deskAnchor.GetChild(i).gameObject);
            const float w = 0.9f, d = 0.42f, t = 0.035f, leg = 0.035f;
            SharedShapes.Box(deskAnchor, "Desk Top", new Vector3(0f, DeskTop - t / 2f, 0f), new Vector3(w, t, d), look.wood);
            for (int i = 0; i < 4; i++)
            {
                float x = (i % 2 == 0 ? -1f : 1f) * (w / 2f - leg);
                float z = (i < 2 ? -1f : 1f) * (d / 2f - leg);
                SharedShapes.Box(deskAnchor, "Desk Leg " + (i + 1), new Vector3(x, (DeskTop - t) / 2f, z), new Vector3(leg, DeskTop - t, leg), look.wood);
            }
            // Slanted letter tray at the front half of the desk.
            var tray = SharedShapes.Node(deskAnchor, "Letter Tray", new Vector3(0f, DeskTop + 0.035f, -0.05f), Quaternion.Euler(60f, 0f, 0f)).transform;
            SharedShapes.Box(tray, "Tray Board", new Vector3(0f, 0f, 0.008f), new Vector3(w - 0.06f, 0.2f, 0.012f), look.wood);
            SharedShapes.Box(tray, "Tray Lip", new Vector3(0f, -0.1f, -0.006f), new Vector3(w - 0.06f, 0.012f, 0.03f), look.wood);
            SharedShapes.Text(deskAnchor, "Desk Title", look.font, "LETTERS", new Vector3(0f, DeskTop - 0.016f, -d / 2f - 0.0015f),
                              new Vector2(0.3f, 0.03f), 0.016f, new Color(0.95f, 0.9f, 0.8f), TextAlignmentOptions.Center, false, FontStyles.Bold);

            // The page (hidden until a letter is opened) stands on a wire stand behind the tray.
            var pageRoot = SharedShapes.Node(deskAnchor, "Letter Page", Vector3.zero, Quaternion.identity);
            page = pageRoot.AddComponent<SharedLetterPage>();
            var sheet = SharedShapes.Node(pageRoot.transform, "Sheet", new Vector3(0f, DeskTop + 0.16f + 0.27f, 0.1f), Quaternion.Euler(8f, 0f, 0f)).transform;
            page.sheet = sheet;
            page.paper = SharedShapes.Box(sheet, "Paper", new Vector3(0f, 0f, 0.0015f), new Vector3(0.42f, 0.55f, 0.003f), look.paper).transform;
            var pic = SharedShapes.MeshNode(sheet, "Picture", SharedShapes.Quad, new Vector3(0f, 0f, -0.0008f), Quaternion.identity, new Vector3(0.4f, 0.5f, 1f), look.page);
            page.picture = pic;
            page.title = SharedShapes.Text(sheet, "Title", look.font, "", new Vector3(0f, 0.27f, -0.0015f), new Vector2(0.38f, 0.04f), 0.02f,
                                           SharedPalette.Ink, TextAlignmentOptions.Center, true, FontStyles.Bold);
            page.bodyText = SharedShapes.Text(sheet, "Body", look.font, "", new Vector3(0f, 0f, -0.0015f), new Vector2(0.37f, 0.46f), 0.022f,
                                              SharedPalette.Ink, TextAlignmentOptions.TopLeft, true);
            var stand = SharedShapes.Node(pageRoot.transform, "Stand", Vector3.zero, Quaternion.identity);
            SharedShapes.Box(stand.transform, "Wire", new Vector3(0f, DeskTop + 0.1f, 0.12f), new Vector3(0.008f, 0.2f, 0.008f), look.wood);
            SharedShapes.Box(stand.transform, "Foot", new Vector3(0f, DeskTop + 0.004f, 0.12f), new Vector3(0.12f, 0.008f, 0.08f), look.wood);
            page.stand = stand;
            sheet.gameObject.SetActive(false);
            stand.SetActive(false);
        }

        // ------------------------------------------------------------------
        // Redraw
        // ------------------------------------------------------------------

        public void Render(SharedView view)
        {
            look.EnsureDefaults();
            Clear();
            var content = SharedShapes.Node(transform, ContentName, Vector3.zero, Quaternion.identity);
            content.SetActive(false);   // interactables are injected before anything wakes up
            _content = content.transform;
            int onObjects = 0, onBoard = 0, tags = 0;
            if (view != null)
            {
                RenderNotes(view, out onObjects, out onBoard);
                tags = RenderTags(view);
                RenderLetters(view);
            }
            content.SetActive(true);
            if (page != null && page.CurrentLetter != null)
            {
                var l = view != null ? view.FindLetter(page.CurrentLetter) : null;
                if (l == null || !l.HasPage) page.Hide();
            }
            LastRender = "notes " + (onObjects + onBoard) + " (objects " + onObjects + ", board " + onBoard + "), letters " +
                         _envelopes.Count + ", tags " + tags;
        }

        void Clear()
        {
            _envelopes.Clear();
            foreach (var t in _tags) SharedShapes.Destroy(t);
            _tags.Clear();
            for (int i = transform.childCount - 1; i >= 0; i--)
            {
                var c = transform.GetChild(i);
                if (c.name == ContentName) { c.name = ContentName + " (old)"; SharedShapes.Destroy(c.gameObject); }
            }
            // Tags baked in the Editor preview live under the objects.
            foreach (var o in mapObjects)
            {
                if (o == null) continue;
                for (int i = o.childCount - 1; i >= 0; i--)
                    if (o.GetChild(i).name == TagName) SharedShapes.Destroy(o.GetChild(i).gameObject);
            }
            _content = null;
        }

        Transform ObjectFor(string assetId)
        {
            if (string.IsNullOrEmpty(assetId)) return null;
            for (int i = 0; i < mapAssetIds.Length && i < mapObjects.Length; i++)
                if (mapAssetIds[i] == assetId && mapObjects[i] != null) return mapObjects[i];
            return null;
        }

        string ObjectLabel(SharedView view, string assetId, Transform obj)
        {
            foreach (var o in view.objects) if (o != null && o.asset_id == assetId && !string.IsNullOrEmpty(o.label)) return o.label;
            return obj != null ? obj.name.Replace('_', ' ') : "";
        }

        /// <summary>World-aligned box of a room object from its RoomKit collider, ignoring the reveal's scale
        /// (objects may be arbitrarily rotated, so local "up" is not world up).</summary>
        static Bounds WorldBox(Transform obj, out Matrix4x4 m)
        {
            m = Matrix4x4.TRS(obj.position, obj.rotation, Vector3.one);
            var box = obj.GetComponent<BoxCollider>();
            var c = box != null ? box.center : Vector3.zero;
            var h = (box != null ? box.size : new Vector3(0.4f, 0.4f, 0.4f)) * 0.5f;
            var b = new Bounds(m.MultiplyPoint3x4(c), Vector3.zero);
            for (int i = 0; i < 8; i++)
                b.Encapsulate(m.MultiplyPoint3x4(c + new Vector3((i & 1) != 0 ? h.x : -h.x, (i & 2) != 0 ? h.y : -h.y, (i & 4) != 0 ? h.z : -h.z)));
            return b;
        }

        /// <summary>Where the ray from the box centre towards the spawn leaves the box (xz), at the centre's height.</summary>
        Vector3 FrontFace(Bounds wb)
        {
            var dir = Flat(spawn - wb.center);
            if (dir.sqrMagnitude < 1e-4f) return wb.center;
            dir.Normalize();
            float tx = Mathf.Abs(dir.x) > 1e-4f ? wb.extents.x / Mathf.Abs(dir.x) : float.MaxValue;
            float tz = Mathf.Abs(dir.z) > 1e-4f ? wb.extents.z / Mathf.Abs(dir.z) : float.MaxValue;
            return wb.center + dir * Mathf.Min(tx, tz);
        }

        Vector3 Flat(Vector3 v) { return new Vector3(v.x, 0f, v.z); }

        Quaternion FacingSpawn(Vector3 worldPos)
        {
            var away = Flat(worldPos - spawn);
            if (away.sqrMagnitude < 1e-4f) away = Vector3.forward;
            return Quaternion.LookRotation(away.normalized, Vector3.up);
        }

        void RenderNotes(SharedView view, out int onObjects, out int onBoard)
        {
            onObjects = 0;
            onBoard = 0;
            var used = new Dictionary<Transform, int>();
            var boardNotes = new List<SharedNote>();
            foreach (var note in view.notes)
            {
                if (note == null || string.IsNullOrEmpty(note.text)) continue;
                Transform target = null;
                string targetAsset = "";
                // Prefer an object no other note sits beside yet.
                foreach (var id in note.asset_ids)
                {
                    var o = ObjectFor(id);
                    if (o == null) continue;
                    if (target == null) { target = o; targetAsset = id; }
                    if (!used.ContainsKey(o)) { target = o; targetAsset = id; break; }
                }
                if (target == null) { boardNotes.Add(note); continue; }
                int k;
                used.TryGetValue(target, out k);
                used[target] = k + 1;
                PlaceNoteBeside(view, note, target, targetAsset, k);
                onObjects++;
            }
            if (boardNotes.Count > 0) onBoard = BuildBoard(view, boardNotes);
        }

        void PlaceNoteBeside(SharedView view, SharedNote note, Transform obj, string assetId, int index)
        {
            Matrix4x4 m;
            var wb = WorldBox(obj, out m);
            var wc = wb.center;
            float r = Mathf.Max(wb.extents.x, wb.extents.z);
            var toSpawn = Flat(spawn - wc);
            if (toSpawn.sqrMagnitude < 1e-4f) toSpawn = Vector3.back;
            toSpawn.Normalize();
            var side = Vector3.Cross(Vector3.up, toSpawn).normalized * (index % 2 == 0 ? 1f : -1f);
            float reach = r * 0.75f + 0.28f + 0.12f * (index / 2);
            var p = new Vector3(wc.x, floorY, wc.z) + toSpawn * reach + side * (r * 0.8f + 0.22f);
            var fromSpawn = Flat(p - spawn);
            if (fromSpawn.magnitude < 0.75f) p = spawn + (fromSpawn.sqrMagnitude > 1e-4f ? fromSpawn.normalized : Vector3.forward) * 0.75f + Vector3.up * (floorY - spawn.y);

            var stand = SharedShapes.Node(_content, "Note " + (note.note_id.Length > 0 ? note.note_id : assetId), p, FacingSpawn(p)).transform;
            SharedShapes.Box(stand, "Stand Foot", new Vector3(0f, 0.008f, 0f), new Vector3(0.2f, 0.016f, 0.14f), look.wood);
            SharedShapes.Box(stand, "Stand Pole", new Vector3(0f, 0.47f, 0.02f), new Vector3(0.018f, 0.92f, 0.018f), look.wood);
            string header = AuthorHeader(note.author);
            string footer = "beside the " + SharedShapes.Clip(ObjectLabel(view, assetId, obj), 40);
            SharedShapes.Card(stand, "Card", look, new Vector3(0f, 1.05f, 0f), Quaternion.Euler(28f, 0f, 0f), new Vector2(0.34f, 0.23f),
                              session != null ? session.ColorFor(note.author) : SharedPalette.Account1, header, SharedShapes.Clip(note.text, 420), footer);
        }

        string AuthorHeader(string author)
        {
            if (session == null) return author;
            string name = session.DisplayNameFor(author);
            return session.LabelFor(author) + (name.Length > 0 ? " - " + name : "");
        }

        int BuildBoard(SharedView view, List<SharedNote> notes)
        {
            if (boardAnchor == null) return 0;
            var board = SharedShapes.Node(_content, "Notes Board", boardAnchor.position, boardAnchor.rotation).transform;
            const float bw = 0.84f, bh = 0.62f, cy = 1.36f;
            SharedShapes.Box(board, "Leg L", new Vector3(-0.3f, cy / 2f, 0.03f), new Vector3(0.03f, cy, 0.03f), look.wood);
            SharedShapes.Box(board, "Leg R", new Vector3(0.3f, cy / 2f, 0.03f), new Vector3(0.03f, cy, 0.03f), look.wood);
            var face = SharedShapes.Node(board, "Board", new Vector3(0f, cy, 0f), Quaternion.Euler(10f, 0f, 0f)).transform;
            SharedShapes.Box(face, "Frame", new Vector3(0f, 0f, 0.012f), new Vector3(bw + 0.04f, bh + 0.04f, 0.024f), look.wood);
            SharedShapes.Box(face, "Cork", new Vector3(0f, 0f, -0.0006f), new Vector3(bw, bh, 0.0012f), look.Tinted(look.color, new Color(0.72f, 0.56f, 0.38f)));
            SharedShapes.Text(face, "Title", look.font, "NOTES", new Vector3(0f, bh / 2f + 0.001f, -0.002f), new Vector2(0.3f, 0.03f), 0.016f,
                              new Color(0.95f, 0.9f, 0.8f), TextAlignmentOptions.Center, false, FontStyles.Bold);
            int shown = Mathf.Min(notes.Count, 4);
            for (int i = 0; i < shown; i++)
            {
                var note = notes[i];
                float x = (i % 2 == 0 ? -1f : 1f) * 0.205f, y = (i < 2 ? 1f : -1f) * 0.15f;
                if (shown == 1) x = 0f;
                if (shown <= 2) y = 0f;
                SharedShapes.Card(face, "Card " + (i + 1), look, new Vector3(x, y, -0.004f), Quaternion.Euler(0f, 0f, (i % 2 == 0 ? -1.5f : 1.2f)),
                                  new Vector2(0.37f, 0.26f), session != null ? session.ColorFor(note.author) : SharedPalette.Account1,
                                  AuthorHeader(note.author), SharedShapes.Clip(note.text, 420), "");
            }
            if (notes.Count > shown)
                SharedShapes.Text(face, "More", look.font, "+" + (notes.Count - shown) + " more", new Vector3(0f, -bh / 2f - 0.001f, -0.002f),
                                  new Vector2(0.3f, 0.03f), 0.014f, new Color(0.95f, 0.9f, 0.8f), TextAlignmentOptions.Center);
            return shown;
        }

        int RenderTags(SharedView view)
        {
            int n = 0;
            foreach (var so in view.objects)
            {
                if (so == null) continue;
                var obj = ObjectFor(so.asset_id);
                if (obj == null) continue;
                Matrix4x4 m;
                var wb = WorldBox(obj, out m);
                var inv = m.inverse;
                // On the face towards the player, at the top of the object (capped at a readable height).
                var world = FrontFace(wb);
                bool tall = wb.max.y > floorY + 1.25f;
                world.y = tall ? floorY + 1.25f : wb.max.y + 0.03f;
                var toward = Flat(spawn - world);
                if (toward.sqrMagnitude > 1e-4f) world += toward.normalized * (tall ? 0.08f : 0.03f);

                var tag = new GameObject(TagName);
                tag.transform.SetParent(obj, false);
                tag.transform.localPosition = inv.MultiplyPoint3x4(world);
                tag.transform.localRotation = Quaternion.Inverse(obj.rotation) * FacingSpawn(world);
                tag.transform.localScale = Vector3.one;
                var card = SharedShapes.Node(tag.transform, "Tent", new Vector3(0f, 0.03f, 0f), Quaternion.Euler(18f, 0f, 0f)).transform;
                var col = session != null ? session.ColorFor(so.contributor) : SharedPalette.Account1;
                SharedShapes.Box(card, "Card", new Vector3(0f, 0f, 0.0015f), new Vector3(0.17f, 0.058f, 0.003f), look.paper);
                SharedShapes.Box(card, "Stripe", new Vector3(-0.079f, 0f, -0.0003f), new Vector3(0.012f, 0.058f, 0.0006f), look.Tinted(look.color, col));
                SharedShapes.Text(card, "Label", look.font, SharedShapes.Clip(so.label, 28), new Vector3(0.006f, 0.011f, -0.0012f),
                                  new Vector2(0.14f, 0.026f), 0.0135f, SharedPalette.Ink, TextAlignmentOptions.MidlineLeft, true, FontStyles.Bold);
                string by = "by " + (session != null ? session.LabelFor(so.contributor) : so.contributor) + (so.editable_by_me ? " - yours" : "");
                SharedShapes.Text(card, "By", look.font, by, new Vector3(0.006f, -0.013f, -0.0012f), new Vector2(0.14f, 0.022f), 0.0115f,
                                  Color.Lerp(col, Color.black, 0.35f), TextAlignmentOptions.MidlineLeft, true);
                _tags.Add(tag);
                n++;
            }
            return n;
        }

        void RenderLetters(SharedView view)
        {
            if (deskAnchor == null) return;
            var letters = new List<SharedLetter>();
            foreach (var l in view.letters) if (l != null && !string.IsNullOrEmpty(l.letter_id)) letters.Add(l);
            var group = SharedShapes.Node(_content, "Letters", deskAnchor.position, deskAnchor.rotation).transform;
            if (letters.Count == 0)
            {
                SharedShapes.Text(group, "Empty", look.font, "No letters yet", new Vector3(0f, DeskTop + 0.004f, -0.05f), new Vector2(0.4f, 0.04f), 0.018f,
                                  new Color(0.95f, 0.9f, 0.8f), TextAlignmentOptions.Center).transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
                return;
            }
            int shown = Mathf.Min(letters.Count, 8);
            int perRow = Mathf.Min(shown, 4);
            for (int i = 0; i < shown; i++)
            {
                int row = i / 4, colIdx = i % 4;
                int inRow = row == 0 ? perRow : shown - 4;
                float x = (colIdx - (inRow - 1) / 2f) * 0.215f;
                var pos = new Vector3(x, DeskTop + 0.045f + row * 0.07f, -0.07f + row * 0.1f);
                BuildEnvelope(group, letters[i], pos, Quaternion.Euler(60f, 0f, 0f));
            }
            if (letters.Count > shown)
                SharedShapes.Text(group, "More", look.font, "+" + (letters.Count - shown) + " more", new Vector3(0f, DeskTop - 0.05f, -0.215f),
                                  new Vector2(0.3f, 0.03f), 0.014f, new Color(0.95f, 0.9f, 0.8f), TextAlignmentOptions.Center);
        }

        void BuildEnvelope(Transform parent, SharedLetter letter, Vector3 localPos, Quaternion localRot)
        {
            const float w = 0.2f, h = 0.12f;
            var rootGo = SharedShapes.Node(parent, "Envelope " + letter.letter_id, localPos, localRot);
            var env = rootGo.AddComponent<SharedEnvelope>();
            env.letterId = letter.letter_id;
            env.opened = letter.opened;
            env.canOpen = letter.can_open && !letter.opened;
            var button = rootGo.AddComponent<SharedPokeButton>();
            button.size = new Vector2(w, h);
            button.payload = letter.letter_id;
            button.pressDepth = 0.006f;

            var body = SharedShapes.Node(rootGo.transform, "Body", Vector3.zero, Quaternion.identity).transform;
            env.body = body;
            button.visual = body;
            var authorCol = session != null ? session.ColorFor(letter.author) : SharedPalette.Account1;
            var recipient = letter.recipients.Length > 0 ? letter.recipients[0] : "";
            var recipientCol = session != null ? session.ColorFor(recipient) : SharedPalette.Account2;
            SharedShapes.Box(body, "Paper", new Vector3(0f, 0f, 0.003f), new Vector3(w, h, 0.006f), look.envelope);
            var pivot = SharedShapes.Node(body, "Flap Pivot", new Vector3(0f, h / 2f, -0.0004f), Quaternion.identity).transform;
            SharedShapes.MeshNode(pivot, "Flap", SharedShapes.Flap, Vector3.zero, Quaternion.identity, new Vector3(w, h * 0.58f, 1f),
                              look.Tinted(look.envelope, new Color(0.86f, 0.79f, 0.64f)));
            env.flapPivot = pivot;
            var seal = SharedShapes.MeshNode(body, "Seal", SharedShapes.Cylinder, new Vector3(0f, h / 2f - h * 0.58f + 0.007f, -0.003f),
                                         Quaternion.Euler(90f, 0f, 0f), new Vector3(0.026f, 0.0025f, 0.026f), look.Tinted(look.color, authorCol));
            env.seal = seal.gameObject;
            seal.gameObject.SetActive(!letter.opened);

            string to = "For " + (session != null ? session.RecipientLabels(letter) : recipient);
            SharedShapes.Text(body, "To", look.font, to, new Vector3(0f, -0.036f, -0.0012f), new Vector2(w - 0.02f, 0.02f), 0.0145f,
                              SharedPalette.Ink, TextAlignmentOptions.Center, true, FontStyles.Bold);
            string from = "from " + (session != null ? session.LabelFor(letter.author) : letter.author) +
                          (string.IsNullOrEmpty(letter.title) ? "" : " - " + SharedShapes.Clip(letter.title, 28));
            SharedShapes.Text(body, "From", look.font, from, new Vector3(0f, -0.0505f, -0.0012f), new Vector2(w - 0.02f, 0.013f), 0.0095f,
                              new Color(0.34f, 0.31f, 0.28f), TextAlignmentOptions.Center, true);
            string resting = letter.opened ? (letter.HasPage ? "opened - tap to read" : "opened") :
                             (letter.can_open ? "sealed - tap to open" : "sealed");
            env.restingHint = resting;
            env.hint = SharedShapes.Text(rootGo.transform, "Hint", look.font, resting, new Vector3(0f, -h / 2f - 0.016f, -0.001f),
                                         new Vector2(w + 0.03f, 0.02f), 0.011f, letter.can_open && !letter.opened ? Color.Lerp(recipientCol, Color.black, 0.3f) : new Color(0.34f, 0.31f, 0.28f),
                                         TextAlignmentOptions.Center, true);
            var glow = SharedShapes.MeshNode(rootGo.transform, "Glow", SharedShapes.Quad, new Vector3(0f, 0f, 0.012f), Quaternion.identity,
                                         new Vector3(w * 1.7f, h * 2f, 1f), look.glow);
            env.glow = glow;
            env.glowColor = Color.Lerp(recipientCol, Color.white, 0.25f);
            glow.enabled = letter.can_open && !letter.opened;
            if (!glow.enabled) glow.gameObject.SetActive(false);
            if (look.glow != null && look.glow.HasProperty("_Color"))
                glow.sharedMaterial = look.Tinted(look.glow, new Color(env.glowColor.r, env.glowColor.g, env.glowColor.b, 0.6f));

            env.button = button;
            button.Setup();
            button.Pressed += OnEnvelopePressed;
            _envelopes.Add(env);
        }

        SharedEnvelope EnvelopeFor(string letterId)
        {
            foreach (var e in _envelopes) if (e != null && e.letterId == letterId) return e;
            return null;
        }

        void OnEnvelopePressed(SharedPokeButton b)
        {
            if (b == null || session == null) return;
            if (page != null && page.Visible && page.CurrentLetter == b.payload) { page.Hide(); return; }
            session.OpenLetter(b.payload);
        }

        void OnLetterOpened(string letterId)
        {
            var view = session != null ? session.View : null;
            var letter = view != null ? view.FindLetter(letterId) : null;
            if (letter == null) return;
            var env = EnvelopeFor(letterId);
            if (env != null) env.ShowOpened();
            if (page == null) return;
            string heading = string.IsNullOrEmpty(letter.title) ? "From " + session.LabelFor(letter.author) : letter.title;
            page.Show(letterId, heading, env != null ? env.transform : null);
            string body = letter.body;
            if (!string.IsNullOrEmpty(body)) page.SetBody(body);   // shown until the texture arrives
            if (!string.IsNullOrEmpty(letter.texture_url) || string.IsNullOrEmpty(body))
            {
                // The callback may run at once (cached texture) or after the download.
                session.FetchLetterTexture(letter, tex =>
                {
                    if (page == null || page.CurrentLetter != letterId) return;
                    if (tex != null) page.SetTexture(tex);
                    else page.SetBody(string.IsNullOrEmpty(body) ? "This letter's page can't be loaded right now." : body);
                });
            }
        }

        void OnLetterRefused(string letterId, string reason)
        {
            var env = EnvelopeFor(letterId);
            if (env == null) return;
            var letter = session != null && session.View != null ? session.View.FindLetter(letterId) : null;
            string msg = letter != null && !letter.can_open && !letter.opened
                ? "Only " + session.RecipientLabels(letter) + " can open this"
                : SharedShapes.Clip(reason, 60);
            env.Refuse(msg);
        }
    }
}
