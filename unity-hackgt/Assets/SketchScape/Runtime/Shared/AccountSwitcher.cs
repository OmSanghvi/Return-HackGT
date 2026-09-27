// SketchScape AccountSwitcher — the physical "Account 1 / Account 2" control by the spawn point.
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// A small wooden pedestal with a slanted plate and one badge button per account in the account's
// colour. Poke a badge (hands) or select it with a ray (controllers) to view the room as that
// account: SharedRoomSession.SwitchTo re-reads the shared view and the layer redraws. The active
// badge is lit with a ring; the plate says who is viewing and whether the data is live.
// Build() runs when RoomKit bakes the room; at runtime it only reacts to events.
using System.Collections.Generic;
using TMPro;
using UnityEngine;

namespace SketchScape
{
    [DisallowMultipleComponent]
    public class AccountSwitcher : MonoBehaviour
    {
        public SharedRoomSession session;
        public SharedPokeButton[] badges = new SharedPokeButton[0];
        public Renderer[] badgeFaces = new Renderer[0];
        public GameObject[] activeRings = new GameObject[0];
        public TextMeshPro[] badgeNames = new TextMeshPro[0];
        public TextMeshPro status;
        [HideInInspector] public SharedLayerLook look = new SharedLayerLook();

        string _shownStatus = "";

        /// <summary>Builds pedestal, plate and badges under this transform (its +Z points away from the viewer).</summary>
        public void Build(SharedRoomSession owner, SharedLayerLook withLook)
        {
            session = owner;
            look = withLook;
            for (int i = transform.childCount - 1; i >= 0; i--) SharedShapes.Destroy(transform.GetChild(i).gameObject);
            var cfg = owner.config;
            int n = Mathf.Clamp(cfg.accounts.Length, 1, 4);

            float plateW = Mathf.Max(0.36f, 0.17f * n + 0.03f);
            SharedShapes.Box(transform, "Pedestal Base", new Vector3(0f, 0.012f, 0f), new Vector3(0.26f, 0.024f, 0.22f), look.wood);
            SharedShapes.Box(transform, "Pedestal Column", new Vector3(0f, 0.47f, 0.02f), new Vector3(0.09f, 0.92f, 0.09f), look.wood);
            var plate = SharedShapes.Node(transform, "Plate", new Vector3(0f, 0.98f, 0f), Quaternion.Euler(55f, 0f, 0f)).transform;
            SharedShapes.Box(plate, "Plate Board", new Vector3(0f, 0f, 0.0125f), new Vector3(plateW, 0.23f, 0.025f), look.wood);
            SharedShapes.Box(plate, "Plate Face", new Vector3(0f, 0f, -0.0004f), new Vector3(plateW - 0.02f, 0.21f, 0.0008f), look.paper);
            SharedShapes.Text(plate, "Title", look.font, "VIEWING AS", new Vector3(0f, 0.083f, -0.0015f),
                              new Vector2(plateW - 0.04f, 0.03f), 0.017f, SharedPalette.Ink, TextAlignmentOptions.Center, false, FontStyles.Bold);
            status = SharedShapes.Text(plate, "Status", look.font, "", new Vector3(0f, -0.083f, -0.0015f),
                                       new Vector2(plateW - 0.04f, 0.03f), 0.0125f, new Color(0.3f, 0.28f, 0.26f), TextAlignmentOptions.Center, true);

            var buttons = new List<SharedPokeButton>();
            var faces = new List<Renderer>();
            var rings = new List<GameObject>();
            var names = new List<TextMeshPro>();
            const float bw = 0.15f, bh = 0.08f, depth = 0.018f;
            for (int i = 0; i < n; i++)
            {
                string account = cfg.accounts[i];
                string label = i < cfg.labels.Length && !string.IsNullOrEmpty(cfg.labels[i]) ? cfg.labels[i] : "Account " + (i + 1);
                var col = i == 1 ? SharedPalette.Account2 : SharedPalette.Account1;
                float x = (i - (n - 1) / 2f) * (bw + 0.02f);
                var buttonGo = SharedShapes.Node(plate, "Badge " + label, new Vector3(x, 0.004f, -depth), Quaternion.identity);
                var button = buttonGo.AddComponent<SharedPokeButton>();
                button.size = new Vector2(bw, bh);
                button.payload = account;
                button.pressDepth = 0.009f;
                var visual = SharedShapes.Node(buttonGo.transform, "Visual", Vector3.zero, Quaternion.identity).transform;
                var face = SharedShapes.Box(visual, "Badge", new Vector3(0f, 0f, depth / 2f), new Vector3(bw, bh, depth), look.Tinted(look.color, col));
                SharedShapes.Text(visual, "Label", look.font, label, new Vector3(0f, 0.012f, -0.0012f),
                                  new Vector2(bw - 0.014f, 0.034f), 0.021f, Color.white, TextAlignmentOptions.Center, true, FontStyles.Bold);
                var who = SharedShapes.Text(visual, "Name", look.font, account, new Vector3(0f, -0.019f, -0.0012f),
                                            new Vector2(bw - 0.014f, 0.022f), 0.012f, new Color(1f, 1f, 1f, 0.9f), TextAlignmentOptions.Center, true);
                var ring = SharedShapes.Box(buttonGo.transform, "Active Ring", new Vector3(0f, 0f, depth - 0.001f),
                                            new Vector3(bw + 0.014f, bh + 0.014f, 0.003f), look.Tinted(look.color, Color.Lerp(col, Color.white, 0.55f)));
                var hover = SharedShapes.Box(buttonGo.transform, "Hover", new Vector3(0f, 0f, depth - 0.0005f),
                                             new Vector3(bw + 0.008f, bh + 0.008f, 0.002f), look.Tinted(look.color, Color.white));
                button.visual = visual;
                button.hoverHighlight = hover.gameObject;
                hover.gameObject.SetActive(false);
                button.Setup();
                buttons.Add(button);
                faces.Add(face);
                rings.Add(ring.gameObject);
                names.Add(who);
            }
            badges = buttons.ToArray();
            badgeFaces = faces.ToArray();
            activeRings = rings.ToArray();
            badgeNames = names.ToArray();
            Refresh();
        }

        void OnEnable()
        {
            if (session == null) session = GetComponentInParent<SharedRoomSession>();
            foreach (var b in badges) if (b != null) b.Pressed += OnBadge;
            if (session != null)
            {
                session.AccountChanged += OnAccount;
                session.ViewChanged += OnView;
                session.StatusChanged += Refresh;
            }
            Refresh();
        }

        void OnDisable()
        {
            foreach (var b in badges) if (b != null) b.Pressed -= OnBadge;
            if (session != null)
            {
                session.AccountChanged -= OnAccount;
                session.ViewChanged -= OnView;
                session.StatusChanged -= Refresh;
            }
        }

        void OnDestroy()
        {
            if (look != null && Application.isPlaying) look.Release();
        }

        void OnBadge(SharedPokeButton b)
        {
            if (session != null && b != null) session.SwitchTo(b.payload);
        }

        void OnAccount(string account) { Refresh(); }
        void OnView(SharedView view) { Refresh(); }

        /// <summary>Redraws the active badge, colours from the view and the status line.</summary>
        public void Refresh()
        {
            if (session == null) return;
            string current = session.CurrentAccount;
            if (string.IsNullOrEmpty(current)) current = session.config.default_account;
            for (int i = 0; i < badges.Length; i++)
            {
                if (badges[i] == null) continue;
                string account = badges[i].payload;
                bool active = account == current;
                var col = session.ColorFor(account);
                if (i < badgeFaces.Length && badgeFaces[i] != null && look != null && look.color != null)
                    badgeFaces[i].sharedMaterial = look.Tinted(look.color, active ? col : Color.Lerp(col, new Color(0.25f, 0.25f, 0.27f), 0.55f));
                if (i < activeRings.Length && activeRings[i] != null && activeRings[i].activeSelf != active) activeRings[i].SetActive(active);
                if (i < badgeNames.Length && badgeNames[i] != null)
                {
                    string name = session.DisplayNameFor(account);
                    string text = active ? (name.Length > 0 ? name + " - viewing" : "viewing") : (name.Length > 0 ? name : account);
                    if (badgeNames[i].text != text) badgeNames[i].text = text;
                }
            }
            if (status == null) return;
            bool offline = !string.IsNullOrEmpty(session.LastError);
            string src = session.Source == "live" ? (offline ? "offline - last synced" : "live")
                       : (session.Source == "snapshot" ? "offline copy" : "no data yet");
            if (session.Busy) src += " - syncing";
            string line = session.LabelFor(current) + " - " + src;
            if (line != _shownStatus) { _shownStatus = line; status.text = line; }
        }
    }
}
