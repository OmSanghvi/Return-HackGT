using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

public class SceneLoader : MonoBehaviour
{
    public GameObject housePrefab;
    public GameObject treePrefab;

    private string backendUrl = "http://127.0.0.1:8000/sketch";

    void Start()
    {
        StartCoroutine(LoadSceneFromBackend());
    }

    IEnumerator LoadSceneFromBackend()
    {
        Texture2D texture = Resources.Load<Texture2D>("hackgttest");
        if (texture == null)
        {
            Debug.LogError("Missing file in Assets/Resources: hackgttest.png");
            yield break;
        }

        if (!texture.isReadable)
        {
            Debug.LogError("Enable Read/Write Enabled on the image.");
            yield break;
        }

        byte[] bytes = texture.EncodeToPNG();
        WWWForm form = new WWWForm();
        form.AddBinaryData("sketch", bytes, "hackgttest.png", "image/png");

        using (UnityWebRequest request = UnityWebRequest.Post(backendUrl, form))
        {
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Backend error: " + request.error);
                yield break;
            }

            Debug.Log("Response: " + request.downloadHandler.text);

            SceneResponse response = JsonUtility.FromJson<SceneResponse>(request.downloadHandler.text);

            if (response == null || response.objects == null)
            {
                Debug.LogError("Could not parse scene data.");
                yield break;
            }

            foreach (SceneObject obj in response.objects)
            {
                SpawnObject(obj);
            }
        }
    }

    void SpawnObject(SceneObject obj)
    {
        GameObject prefab = obj.type switch
        {
            "house" => housePrefab,
            "tree" => treePrefab,
            _ => null
        };

        if (prefab == null)
        {
            Debug.LogWarning("No prefab for type: " + obj.type);
            return;
        }

        Vector3 pos = new Vector3(obj.position[0], obj.position[1], obj.position[2]);
        Vector3 scale = new Vector3(obj.scale[0], obj.scale[1], obj.scale[2]);

        GameObject spawned = Instantiate(prefab, pos, Quaternion.identity);
        spawned.transform.localScale = scale;
    }
}

[System.Serializable]
public class SceneResponse
{
    public SceneObject[] objects;
}

[System.Serializable]
public class SceneObject
{
    public string id;
    public string type;
    public float[] position;
    public float[] scale;
}