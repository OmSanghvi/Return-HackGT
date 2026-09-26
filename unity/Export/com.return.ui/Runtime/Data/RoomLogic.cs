using System;
using System.Collections.Generic;
using System.Linq;

namespace Return.Data
{
    /// <summary>Pure room rules and the demo simulator. Port of web-app/src/data/store.ts. No Unity types, so it is unit-testable.</summary>
    public static class RoomLogic
    {
        public static readonly Person Me = new Person { name = "Dylan Houle", email = "dylan@return.world" };
        public const string MeId = "me";

        public static readonly Person[] KnownPeople =
        {
            new Person { name = "Mom", email = "maria.houle@gmail.com" },
            new Person { name = "Sam Park", email = "sam.park@gatech.edu" },
            new Person { name = "Samira Ali", email = "samira@hey.com" },
            new Person { name = "Ava Lin", email = "ava@lin.dev" },
            new Person { name = "Jordan Reyes", email = "jordan@reyes.me" },
        };

        public const long Min = 60_000, Hour = 60 * Min;
        public const long PeopleEtaMs = 5000, BuildMs = 18_000;
        // ponytail: the demo simulator only; a real backend replaces tick/advance with server state.
        static readonly string[] Notes =
        {
            "The dock at sunset, every single night.",
            "I still hear the screen door.",
            "We stayed out until the fireflies came.",
        };

        static readonly Random Rng = new Random();
        public static string Uid() => Guid.NewGuid().ToString("N").Substring(0, 8);

        public static string NameFor(string email)
        {
            var p = KnownPeople.FirstOrDefault(k => k.email == email);
            return p != null ? p.name : email.Split('@')[0];
        }

        public static Member NewMember(string email, long now, MemberStatus status = MemberStatus.Invited, int count = 0, string note = null, bool owner = false, long? invitedAt = null)
            => new Member { id = Uid(), name = NameFor(email), email = email, status = status, count = count, note = note, isOwner = owner, invitedAt = invitedAt ?? now };

        static Member MeMember(long now, MemberStatus status, int count = 0, bool owner = false, string note = null, long? invitedAt = null)
            => new Member { id = MeId, name = Me.name, email = Me.email, status = status, count = count, isOwner = owner, note = note, invitedAt = invitedAt ?? now - 30 * Hour };

        public static List<Room> Seed(long now)
        {
            Room R(string id, string title, string place, string date, SceneKey scene, Phase phase, float progress, long age, string invitedBy, params Member[] members)
                => new Room { id = id, title = title, place = place, date = date, scene = scene, phase = phase, progress = progress, createdAt = now - age, invitedBy = invitedBy, members = members.ToList() };

            return new List<Room>
            {
                R("lake-house", "The lake house", "Lake Norman", "July 14, 2019", SceneKey.Meadow, Phase.Ready, 1, 72 * Hour, null,
                    MeMember(now, MemberStatus.Done, 4, true),
                    NewMember("maria.houle@gmail.com", now, MemberStatus.Done, 5, Notes[0]),
                    NewMember("sam.park@gatech.edu", now, MemberStatus.Done, 4)),
                R("grandmas-porch", "Grandma's porch", "Asheville", null, SceneKey.Home, Phase.Collecting, 0, 26 * Hour, null,
                    MeMember(now, MemberStatus.Done, 4, true, Notes[1]),
                    NewMember("maria.houle@gmail.com", now, MemberStatus.Done, 5),
                    NewMember("sam.park@gatech.edu", now, invitedAt: now - 2 * Hour)),
                R("last-summer", "Last day of summer", "Tybee Island", null, SceneKey.Beach, Phase.Building, 0.35f, 5 * Hour, null,
                    MeMember(now, MemberStatus.Done, 6, true),
                    NewMember("jordan@reyes.me", now, MemberStatus.Done, 5)),
                R("ava-graduation", "Ava's graduation", "Athens", null, SceneKey.Clouds, Phase.Collecting, 0, 3 * Hour, "Ava Lin",
                    NewMember("ava@lin.dev", now, MemberStatus.Done, 7, owner: true),
                    MeMember(now, MemberStatus.Invited, invitedAt: now - 3 * Hour)),
            };
        }

        /// <summary>"vase, porch swing" -> [vase, porch swing]. Caps match the backend: 8 objects, 100 chars each.</summary>
        public static List<string> ParseObjects(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return new List<string>();
            return s.Split(',').Select(x => x.Trim()).Select(x => x.Length > 100 ? x.Substring(0, 100) : x)
                .Where(x => x.Length > 0).Distinct().Take(8).ToList();
        }

        public static Member Mine(Room r) => r.members.FirstOrDefault(m => m.id == MeId);
        public static List<Member> Pending(Room r) => r.members.Where(m => m.status != MemberStatus.Done).ToList();
        public static bool IsMine(Room r) => Mine(r)?.isOwner == true;

        public enum Route { Add, Room }
        /// <summary>Where a room opens, from its status.</summary>
        public static Route RouteForRoom(Room r)
            => r.phase == Phase.Collecting && Mine(r)?.status != MemberStatus.Done ? Route.Add : Route.Room;

        /// <summary>Everyone who hasn't finished gets a simulated arrival time, staggered.</summary>
        public static void ScheduleOthers(Room r, long now)
        {
            int i = 0;
            foreach (var m in r.members)
                if (m.status != MemberStatus.Done && m.id != MeId && m.etaAt == 0) m.etaAt = now + PeopleEtaMs * ++i;
        }

        /// <summary>Simulator step: people arrive, building advances, ready lands. Returns true if anything changed. Mutates in place.</summary>
        public static bool Tick(List<Room> rooms, long now, long dtMs)
        {
            bool changed = false;
            foreach (var r in rooms)
            {
                if (r.phase == Phase.Collecting)
                {
                    if (Mine(r)?.status != MemberStatus.Done) continue;
                    bool arrived = false;
                    foreach (var m in r.members)
                    {
                        if (m.etaAt != 0 && m.etaAt <= now && m.status != MemberStatus.Done)
                        {
                            m.status = MemberStatus.Done;
                            m.count = 3 + m.name.Length % 5;
                            m.note = Notes[m.name.Length % Notes.Length];
                            m.etaAt = 0;
                            arrived = true;
                        }
                    }
                    if (!arrived) continue;
                    changed = true;
                    if (r.members.All(m => m.status == MemberStatus.Done)) { r.phase = Phase.Building; r.progress = 0; }
                }
                else if (r.phase == Phase.Building)
                {
                    changed = true;
                    r.progress = Math.Min(1f, r.progress + (float)dtMs / BuildMs);
                    if (r.progress >= 1f) { r.progress = 1f; r.phase = Phase.Ready; }
                }
            }
            return changed;
        }

        /// <summary>Demo fast-forward: one visible step for the given room.</summary>
        public static void Advance(Room r, long now)
        {
            if (r.phase == Phase.Building) { r.progress = 1; r.phase = Phase.Ready; return; }
            if (r.phase != Phase.Collecting) return;
            var next = Pending(r).FirstOrDefault(m => m.id != MeId);
            if (next == null) return;
            next.etaAt = now;
            Tick(new List<Room> { r }, now, 0);
        }

        public static string AgoText(long t, long now)
        {
            long m = (long)Math.Round((now - t) / (double)Min);
            if (m < 1) return "just now";
            if (m < 60) return m + " minute" + (m == 1 ? "" : "s") + " ago";
            long h = (long)Math.Round(m / 60.0);
            return h + " hour" + (h == 1 ? "" : "s") + " ago";
        }

        /// <summary>First name, or "N people" when several are pending (for "Waiting for ...").</summary>
        public static string WaitingOn(Room r)
        {
            var p = Pending(r).Where(m => m.id != MeId).ToList();
            return p.Count == 1 ? p[0].name.Split(' ')[0] : p.Count + " people";
        }
    }
}
