using UnityEngine;

/// <summary>
/// Deliberately narrow entrypoint for Unity MCP/editor automation. An MCP tool
/// may configure these serialized fields and invoke the context menu, but it
/// cannot call arbitrary methods or address unregistered objects.
/// </summary>
[DisallowMultipleComponent]
[RequireComponent(typeof(SceneInteractionController))]
public sealed class SketchScapeMcpBridge : MonoBehaviour
{
    [SerializeField] private string targetId = "tree_1";
    [SerializeField] private string action = SceneInteractionController.ScaleBy;
    [SerializeField] private Vector3 value = new Vector3(1f, 2f, 1f);
    [SerializeField] private bool routeThroughBackend = true;

    private SceneInteractionController controller;

    private void Awake()
    {
        controller = GetComponent<SceneInteractionController>();
    }

    [ContextMenu("Execute Configured Safe Action")]
    public void ExecuteConfiguredAction()
    {
        controller = controller != null ? controller : GetComponent<SceneInteractionController>();
        if (routeThroughBackend && Application.isPlaying)
        {
            controller.RequestBackendAction(targetId, action, value);
            return;
        }

        controller.RebuildRegistry();
        if (!controller.TryExecuteLocalAction(targetId, action, value, out string error))
        {
            Debug.LogWarning("SketchScape MCP action rejected: " + error, this);
        }
    }

    [ContextMenu("Log Named Interactive Registry")]
    public void LogRegistry()
    {
        controller = controller != null ? controller : GetComponent<SceneInteractionController>();
        Debug.Log(controller.GetRegistryJson(), this);
    }
}
