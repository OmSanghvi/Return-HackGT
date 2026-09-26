using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace Return.Data
{
    /// <summary>The seam a real backend implements. UI only talks to this.</summary>
    public interface IRoomStore
    {
        IReadOnlyList<Room> Rooms { get; }
        bool SignedIn { get; }
        event Action Changed;
        Room Get(string id);
        void SignIn(); void SignOut(); void Reset();
        string CreateRoom(string title, IEnumerable<string> emails);
        void Invite(string id, string email); void Uninvite(string id, string memberId); void Resend(string id, string memberId);
        void Join(string id); void Decline(string id);
        void AddPhotos(string id, List<string> photos, string note, List<string> objects = null);
        void StartBuilding(string id); void Rename(string id, string title); void Leave(string id); void Remove(string id);
        void Step(float dtSeconds); void FastForward(string id);
    }

    /// <summary>Demo store: seeded rooms, local actions, a simulator that plays the other people, JSON persistence. Port of the zustand store.</summary>
    public class RoomStore : IRoomStore
    {
        [Serializable] class Saved { public List<Room> rooms; public bool signedIn; }

        readonly string _path;
        Saved _s;
        public Func<long> Clock = () => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        public event Action Changed;

        public IReadOnlyList<Room> Rooms => _s.rooms;
        public bool SignedIn => _s.signedIn;
        public Room Get(string id) => _s.rooms.FirstOrDefault(r => r.id == id);

        /// <summary>persistPath null = in-memory only (tests).</summary>
        public RoomStore(string persistPath = null)
        {
            _path = persistPath;
            try { if (_path != null && File.Exists(_path)) _s = JsonUtility.FromJson<Saved>(File.ReadAllText(_path)); } catch { _s = null; }
            if (_s == null || _s.rooms == null) _s = new Saved { rooms = RoomLogic.Seed(Clock()), signedIn = false };
        }

        public static string DefaultPath => Path.Combine(Application.persistentDataPath, "return-demo-v1.json");

        float _lastSave;

        void Commit(bool persist = true)
        {
            try { if (persist && _path != null) { File.WriteAllText(_path, JsonUtility.ToJson(_s)); _lastSave = Time.realtimeSinceStartup; } } catch (Exception e) { Debug.LogWarning("Return: could not save rooms: " + e.Message); }
            Changed?.Invoke();
        }

        void Patch(string id, Action<Room> fn) { var r = Get(id); if (r == null) return; fn(r); Commit(); }
        void Drop(string id) { _s.rooms.RemoveAll(r => r.id == id); Commit(); }

        public void SignIn() { _s.signedIn = true; Commit(); }
        public void SignOut() { _s.signedIn = false; Commit(); }
        public void Reset() { _s = new Saved { rooms = RoomLogic.Seed(Clock()), signedIn = false }; Commit(); }

        public string CreateRoom(string title, IEnumerable<string> emails)
        {
            long now = Clock();
            var scenes = new[] { SceneKey.Home, SceneKey.Meadow, SceneKey.Plain, SceneKey.Beach, SceneKey.Clouds };
            var room = new Room
            {
                id = RoomLogic.Uid(), title = string.IsNullOrWhiteSpace(title) ? "Untitled room" : title.Trim(),
                scene = scenes[_s.rooms.Count % scenes.Length], phase = Phase.Collecting, createdAt = now,
            };
            room.members.Add(new Member { id = RoomLogic.MeId, name = RoomLogic.Me.name, email = RoomLogic.Me.email, status = MemberStatus.Joined, isOwner = true, invitedAt = now });
            foreach (var e in emails) room.members.Add(RoomLogic.NewMember(e, now));
            _s.rooms.Insert(0, room);
            Commit();
            return room.id;
        }

        public void Invite(string id, string email) => Patch(id, r =>
        {
            if (r.members.Any(m => m.email == email)) return;
            long now = Clock();
            r.members.Add(RoomLogic.NewMember(email, now));
            if (RoomLogic.Mine(r)?.status == MemberStatus.Done) RoomLogic.ScheduleOthers(r, now);
        });

        public void Uninvite(string id, string memberId) => Patch(id, r => r.members.RemoveAll(m => m.id == memberId));
        public void Resend(string id, string memberId) => Patch(id, r => { var m = r.members.FirstOrDefault(x => x.id == memberId); if (m != null) m.invitedAt = Clock(); });
        public void Join(string id) => Patch(id, r => { var m = RoomLogic.Mine(r); if (m != null) m.status = MemberStatus.Joined; });
        public void Decline(string id) => Drop(id);

        public void AddPhotos(string id, List<string> photos, string note, List<string> objects = null) => Patch(id, r =>
        {
            r.photos = new List<string>(photos);
            if (string.IsNullOrEmpty(r.cover) && photos.Count > 0) r.cover = photos[0];
            if (objects != null) r.objects = objects;
            var m = RoomLogic.Mine(r);
            if (m != null) { m.status = MemberStatus.Done; m.count = photos.Count; m.note = string.IsNullOrWhiteSpace(note) ? null : note.Trim(); }
            RoomLogic.ScheduleOthers(r, Clock());
        });

        public void StartBuilding(string id) => Patch(id, r => { r.phase = Phase.Building; r.progress = 0; r.members.RemoveAll(m => m.status != MemberStatus.Done); });
        public void Rename(string id, string title) => Patch(id, r => r.title = title);
        public void Leave(string id) => Drop(id);
        public void Remove(string id) => Drop(id);

        public void Step(float dt)
        {
            if (!RoomLogic.Tick(_s.rooms, Clock(), (long)(dt * 1000f))) return;
            Commit(Time.realtimeSinceStartup - _lastSave > 2f); // progress ticks every frame; write to disk every 2s
        }
        public void FastForward(string id) => Patch(id, r => RoomLogic.Advance(r, Clock()));
    }
}
