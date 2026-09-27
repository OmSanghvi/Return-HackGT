// SketchScape shared layer — data shapes (Return-HackGT docs/WEB_TO_QUEST_PIPELINE.md 1b, 3, 4).
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// JsonUtility mirrors of the contract: field names equal the JSON keys, no nulls/dicts/nested
// arrays. Every field has a default so a partial response still parses.
using System;
using UnityEngine;

namespace SketchScape
{
    /// <summary>The room spec's "shared" block (section 3), copied onto SharedRoomSession by RoomKit.</summary>
    [Serializable]
    public class SharedRoomConfig
    {
        public bool enabled = false;
        public string project_id = "";
        public string api_base = "";
        public string[] accounts = new string[0];
        public string[] labels = new string[0];
        public string default_account = "";
        public string snapshot_resource = "";
    }

    [Serializable]
    public class SharedAccount
    {
        public string id = "";
        public string label = "";
        public string display_name = "";
        public string color = "";
    }

    [Serializable]
    public class SharedNote
    {
        public string note_id = "";
        public string author = "";
        public string text = "";
        public string upload_id = "";
        public string[] asset_ids = new string[0];
        public string created_at = "";
    }

    [Serializable]
    public class SharedLetter
    {
        public string letter_id = "";
        public string author = "";
        public string[] recipients = new string[0];
        public string title = "";
        public bool @sealed = true;   // JSON key "sealed"
        public bool can_open = false;
        public bool opened = false;
        public string body = "";
        public string texture_url = "";

        /// <summary>True when this viewer has the page (body or texture).</summary>
        public bool HasPage { get { return !string.IsNullOrEmpty(body) || !string.IsNullOrEmpty(texture_url); } }
    }

    [Serializable]
    public class SharedObject
    {
        public string asset_id = "";
        public string label = "";
        public string contributor = "";
        public bool editable_by_me = false;
    }

    [Serializable]
    public class SharedBuild
    {
        public string build_id = "";
        public string status = "";
        public string slug = "";
        public string scene_path = "";
        public string apk_path = "";
    }

    /// <summary>GET /v1/rooms/{project_id}/shared as one account (section 1b).</summary>
    [Serializable]
    public class SharedView
    {
        public string project_id = "";
        public string title = "";
        public string viewer = "";
        public string viewer_label = "";
        public SharedAccount[] accounts = new SharedAccount[0];
        public SharedNote[] notes = new SharedNote[0];
        public SharedLetter[] letters = new SharedLetter[0];
        public SharedObject[] objects = new SharedObject[0];
        public SharedBuild latest_build = new SharedBuild();

        public void Normalize()
        {
            if (project_id == null) project_id = "";
            if (title == null) title = "";
            if (viewer == null) viewer = "";
            if (viewer_label == null) viewer_label = "";
            if (accounts == null) accounts = new SharedAccount[0];
            if (notes == null) notes = new SharedNote[0];
            if (letters == null) letters = new SharedLetter[0];
            if (objects == null) objects = new SharedObject[0];
            if (latest_build == null) latest_build = new SharedBuild();
            foreach (var n in notes) if (n != null && n.asset_ids == null) n.asset_ids = new string[0];
            foreach (var l in letters) if (l != null && l.recipients == null) l.recipients = new string[0];
        }

        public SharedLetter FindLetter(string letterId)
        {
            if (string.IsNullOrEmpty(letterId)) return null;
            for (int i = 0; i < letters.Length; i++)
                if (letters[i] != null && letters[i].letter_id == letterId) return letters[i];
            return null;
        }

        public SharedAccount FindAccount(string id)
        {
            for (int i = 0; i < accounts.Length; i++)
                if (accounts[i] != null && accounts[i].id == id) return accounts[i];
            return null;
        }
    }

    [Serializable]
    public class SharedSnapshotView
    {
        public string account = "";
        public SharedView shared = new SharedView();
    }

    /// <summary>The offline copy the runner bakes into Resources/SharedSnapshots/&lt;project_id&gt;.json (section 4).</summary>
    [Serializable]
    public class SharedSnapshot
    {
        public int version = 1;
        public string project_id = "";
        public string fetched_at = "";
        public SharedSnapshotView[] views = new SharedSnapshotView[0];

        public SharedView ViewFor(string account)
        {
            if (views == null) return null;
            for (int i = 0; i < views.Length; i++)
                if (views[i] != null && views[i].account == account && views[i].shared != null) return views[i].shared;
            return null;
        }
    }

    /// <summary>Account colours and labels, from the view when it has them, else defaults.</summary>
    public static class SharedPalette
    {
        public static readonly Color Account1 = new Color32(0xE8, 0xA3, 0x3D, 0xFF);
        public static readonly Color Account2 = new Color32(0x4A, 0xA3, 0xDF, 0xFF);
        public static readonly Color Ink = new Color(0.13f, 0.11f, 0.10f, 1f);
        public static readonly Color Paper = new Color(0.96f, 0.93f, 0.86f, 1f);

        public static Color Parse(string hex, Color fallback)
        {
            Color c;
            if (!string.IsNullOrEmpty(hex) && ColorUtility.TryParseHtmlString(hex.Trim(), out c)) { c.a = 1f; return c; }
            return fallback;
        }
    }
}
