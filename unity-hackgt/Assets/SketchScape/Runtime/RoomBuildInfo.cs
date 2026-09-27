// SketchScape RoomKit — what RoomKit.Build recorded about a room (on the room's root).
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// The Editor RoomKit writes it and reads it back: Finalize(slug, x, z, yaw) takes no spec, so Build
// stores the spec's performance choices and the grabbable object ids here; Finalize follows them and
// stamps finalizedWith; Status reports from it. No runtime behaviour (plain data).
using UnityEngine;

namespace SketchScape
{
    [DisallowMultipleComponent]
    [AddComponentMenu("")]
    public sealed class RoomBuildInfo : MonoBehaviour
    {
        [Tooltip("The room's slug (RoomKit.Build / Finalize / Status argument).")]
        public string slug = "";
        [Tooltip("RoomKit version that built the room.")]
        public string builtWith = "";

        [Header("Spec performance block")]
        public string target = "quest";
        public bool preferQuestLod = true;
        public bool pickups = true;
        public bool questPerformance = true;
        public bool metaSetup = true;

        [Tooltip("Ids (child names under the room root) of the objects that get Meta near + distance grab and a pickup.")]
        public string[] grabbable = new string[0];

        [Tooltip("RoomKit version whose Finalize completed on this room; empty until then (RoomKit.Status 'finalized').")]
        public string finalizedWith = "";
    }
}
