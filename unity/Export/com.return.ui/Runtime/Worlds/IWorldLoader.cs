using System;
using System.Threading.Tasks;
using Return.Data;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// The seam between the hub and whatever a "world" is. Implement it for scenes, Gaussian splats, or a backend download.
    /// Load must leave the world around the viewer (root at the origin, facing the viewer's yaw) and report progress 0..1.
    /// </summary>
    public interface IWorldLoader
    {
        Task LoadAsync(Room room, Transform head, Action<float> progress);
        Task UnloadAsync();
    }
}
