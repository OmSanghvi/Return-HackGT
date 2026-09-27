using Return.Design;
using UnityEngine;

namespace Return.UI
{
    /// <summary>
    /// Replaces HubEnvironment's fogged floor disc with still water that fakes a reflection of the sky
    /// (Return/WaterFloor: fresnel and glints, no reflection camera or grab pass). Perfectly still: the play test asked
    /// for no waves or ripple rings, so nothing here updates per frame.
    /// </summary>
    public class WaterFloor : MonoBehaviour
    {
        const float Radius = 26f;
        Material _mat;

        public static WaterFloor Create(Transform parent)
        {
            var go = new GameObject("Floor"); go.transform.SetParent(parent, false);
            go.AddComponent<MeshFilter>().sharedMesh = SkyBackdrop.Quad();
            go.transform.localRotation = Quaternion.Euler(90, 0, 0); go.transform.localPosition = new Vector3(0, -0.02f, 0); go.transform.localScale = new Vector3(Radius, Radius, 1);
            var wf = go.AddComponent<WaterFloor>();
            wf._mat = ReturnShaders.Create(ReturnShaders.WaterFloor);
            wf._mat.SetColor("_Color", new Color(0.02f, 0.03f, 0.08f, 0.88f));
            wf._mat.SetColor("_Top", (Color)ReturnColorsDusk.SkyTop);
            wf._mat.SetColor("_Bottom", (Color)ReturnColorsDusk.SkyBottom);
            wf._mat.SetFloat("_Radial", 1);
            go.AddComponent<MeshRenderer>().sharedMaterial = wf._mat;
            return wf;
        }

        void OnDestroy() { if (_mat != null) Destroy(_mat); }
    }
}
