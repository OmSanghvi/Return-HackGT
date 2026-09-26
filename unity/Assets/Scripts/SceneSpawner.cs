using UnityEngine;

public class SceneSpawner : MonoBehaviour
{
    public GameObject housePrefab;
    public GameObject treePrefab;

    void Start()
    {
        SpawnScene();
    }

    void SpawnScene()
    {
        SpawnObject("house", new Vector3(3f, 1f, 1f), new Vector3(1f, 1f, 1f));
        SpawnObject("tree", new Vector3(0f, 1f, 0f), new Vector3(1f, 1f, 1f));
    }

    void SpawnObject(string type, Vector3 position, Vector3 scale)
    {
        GameObject prefab = type == "house" ? housePrefab : treePrefab;

        if (prefab == null)
        {
            Debug.LogError("Prefab missing for type: " + type);
            return;
        }

        GameObject obj = Instantiate(prefab, position, Quaternion.identity);
        obj.transform.localScale = scale;
    }
}