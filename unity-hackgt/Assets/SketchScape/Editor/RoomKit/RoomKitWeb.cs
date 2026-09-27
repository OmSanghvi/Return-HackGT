// SketchScape RoomKit — web media cache (Editor only).
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
//
// Every URL is downloaded at most once into Assets/SketchScape/WebCache/ under
// a hash of the URL; the file extension comes from the content's magic bytes
// (not the URL), so Unity picks the right importer. Downloads run in parallel
// with per-request and overall timeouts; failures are reported, never thrown.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace SketchScape
{
    public static class RoomKitWeb
    {
        public const string CacheFolder = "Assets/SketchScape/WebCache";
        const long MaxBytes = 60L * 1024 * 1024;
        const int PerRequestSeconds = 60;
        const int OverallSeconds = 150;

        static HttpClient s_client;

        static HttpClient Client
        {
            get
            {
                if (s_client != null) return s_client;
                var handler = new HttpClientHandler { AllowAutoRedirect = true };
                s_client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(PerRequestSeconds) };
                s_client.DefaultRequestHeaders.UserAgent.ParseAdd("SketchScape-RoomKit/1.0 (HackGT demo; +https://github.com/)");
                return s_client;
            }
        }

        public static string UrlHash(string url)
        {
            using (var sha = SHA1.Create())
            {
                var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(url.Trim()));
                var sb = new StringBuilder();
                for (int i = 0; i < 8; i++) sb.Append(bytes[i].ToString("x2"));
                return sb.ToString();
            }
        }

        /// <summary>Existing cached asset path for this URL, or null.</summary>
        public static string Cached(string url)
        {
            var dir = Path.GetFullPath(CacheFolder);
            if (!Directory.Exists(dir)) return null;
            var hash = UrlHash(url);
            foreach (var f in Directory.GetFiles(dir, hash + ".*"))
            {
                if (f.EndsWith(".meta", StringComparison.OrdinalIgnoreCase)) continue;
                if (new FileInfo(f).Length == 0) continue;
                return CacheFolder + "/" + Path.GetFileName(f);
            }
            return null;
        }

        /// <summary>
        /// Downloads every URL not yet cached (in parallel) and imports it.
        /// Returns url -> asset path for everything available; failures are
        /// appended to <paramref name="failures"/> as short strings.
        /// </summary>
        public static Dictionary<string, string> FetchAll(IEnumerable<string> urls, List<string> failures)
        {
            var result = new Dictionary<string, string>();
            var pending = new List<string>();
            foreach (var raw in urls)
            {
                if (string.IsNullOrWhiteSpace(raw)) continue;
                var url = raw.Trim();
                if (result.ContainsKey(url) || pending.Contains(url)) continue;
                if (!url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
                    !url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                {
                    // Allow a project asset path in place of a URL.
                    if (url.StartsWith("Assets/") && File.Exists(url)) result[url] = url;
                    else failures.Add("bad url " + Short(url));
                    continue;
                }
                var cached = Cached(url);
                if (cached != null) result[url] = cached;
                else pending.Add(url);
            }
            if (pending.Count == 0) return result;

            EnsureFolder(CacheFolder);
            var tasks = new List<Task<byte[]>>();
            foreach (var url in pending) tasks.Add(Download(url));
            try { Task.WaitAll(tasks.ToArray(), TimeSpan.FromSeconds(OverallSeconds)); }
            catch (AggregateException) { /* per-task status is inspected below */ }

            var written = new List<string>();
            for (int i = 0; i < pending.Count; i++)
            {
                var url = pending[i];
                var task = tasks[i];
                if (!task.IsCompleted) { failures.Add("timeout " + Short(url)); continue; }
                if (task.IsFaulted || task.IsCanceled)
                {
                    var ex = task.Exception != null ? task.Exception.GetBaseException() : null;
                    failures.Add("download failed " + Short(url) + (ex != null ? " (" + Short(ex.Message) + ")" : ""));
                    continue;
                }
                var bytes = task.Result;
                var ext = Sniff(bytes);
                if (ext == null) { failures.Add("unsupported media " + Short(url)); continue; }
                var path = CacheFolder + "/" + UrlHash(url) + ext;
                File.WriteAllBytes(path, bytes);
                written.Add(path);
                result[url] = path;
            }
            foreach (var path in written)
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            return result;
        }

        static async Task<byte[]> Download(string url)
        {
            using (var response = await Client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).ConfigureAwait(false))
            {
                if (!response.IsSuccessStatusCode)
                    throw new Exception("HTTP " + (int)response.StatusCode);
                var length = response.Content.Headers.ContentLength;
                if (length.HasValue && length.Value > MaxBytes)
                    throw new Exception("too large (" + length.Value / (1024 * 1024) + " MB)");
                var bytes = await response.Content.ReadAsByteArrayAsync().ConfigureAwait(false);
                if (bytes.Length == 0) throw new Exception("empty body");
                if (bytes.Length > MaxBytes) throw new Exception("too large");
                return bytes;
            }
        }

        /// <summary>File extension from magic bytes, or null when Unity can't import it.</summary>
        public static string Sniff(byte[] b)
        {
            if (b == null || b.Length < 12) return null;
            if (b[0] == 0x89 && b[1] == 0x50 && b[2] == 0x4E && b[3] == 0x47) return ".png";
            if (b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF) return ".jpg";
            if (b[0] == '#' && b[1] == '?') return ".hdr";               // #?RADIANCE / #?RGBE
            if (b[0] == 0x76 && b[1] == 0x2F && b[2] == 0x31 && b[3] == 0x01) return ".exr";
            if (b[0] == 'O' && b[1] == 'g' && b[2] == 'g' && b[3] == 'S') return ".ogg";
            if (b[0] == 'R' && b[1] == 'I' && b[2] == 'F' && b[3] == 'F' &&
                b[8] == 'W' && b[9] == 'A' && b[10] == 'V' && b[11] == 'E') return ".wav";
            if (b[0] == 'I' && b[1] == 'D' && b[2] == '3') return ".mp3";
            if (b[0] == 0xFF && (b[1] & 0xE0) == 0xE0) return ".mp3";    // MPEG frame sync
            if (b[0] == 'f' && b[1] == 'L' && b[2] == 'a' && b[3] == 'C') return null; // FLAC: not importable
            if (b[0] == 'G' && b[1] == 'I' && b[2] == 'F') return null;
            if (b[0] == 'R' && b[1] == 'I' && b[2] == 'F' && b[3] == 'F' && b[8] == 'W' && b[9] == 'E') return null; // WEBP
            return null;
        }

        public static string Short(string s)
        {
            if (s == null) return "";
            s = s.Replace("\n", " ").Replace("\r", " ");
            return s.Length <= 70 ? s : s.Substring(0, 67) + "...";
        }

        public static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            var parent = Path.GetDirectoryName(path).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }
    }
}
