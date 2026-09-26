using Return.Data;

namespace Return.UI
{
    /// <summary>What screens ask of the sky behind them. SkyBackdrop paints it; the VR hub ignores it (the hub owns its own sky).</summary>
    public interface IBackdrop
    {
        void Set(SceneKey scene, bool instant = false);
        void SetMist(float mist);
    }

    public class NullBackdrop : IBackdrop
    {
        public void Set(SceneKey scene, bool instant = false) { }
        public void SetMist(float mist) { }
    }
}
