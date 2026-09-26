using System;
using System.Collections.Generic;
using System.IO;
using Gsplat;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.SpatialTracking;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Locomotion.Teleportation;

/// <summary>
/// Deterministically materializes an exported, backend-validated scene into a
/// saved Unity scene. NemoClaw/Unity MCP invokes this at authoring time only.
/// </summary>
public static class SketchScapeOfflineExperienceBuilder
{
    public const string InputPath = "Assets/SketchScape/Authoring/compiled-scene.json";
    public const string OutputScenePath = "Assets/Generated/SketchScape/Scenes/Experience.unity";
    public const string ArtifactFolder = "Assets/SketchScape/Authoring/Artifacts";
    private const string StarterRigPath = "Assets/Samples/XR Interaction Toolkit/3.0.11/Starter Assets/Prefabs/XR Origin (XR Rig).prefab";
    // The starter rig's teleport interactor only targets this interaction layer.
    private const string TeleportInteractionLayer = "Teleport";

    [MenuItem("Tools/SketchScape/Authoring/Build Offline Experience Scene")]
    public static void BuildOfflineExperienceScene()
    {
        if (!File.Exists(InputPath))
        {
            throw new FileNotFoundException(
                "Export GET /v1/projects/{project_id}/compiled-scene to " + InputPath + " before building.", InputPath);
        }

        string json = File.ReadAllText(InputPath);
        var envelope = JsonUtility.FromJson<OfflineSceneEnvelope>(json);
        if (envelope == null || envelope.scene == null || envelope.scene.objects == null)
        {
            throw new InvalidDataException("The compiled scene export is invalid.");
        }

        EnsureFolder("Assets/Generated");
        EnsureFolder("Assets/Generated/SketchScape");
        EnsureFolder("Assets/Generated/SketchScape/Scenes");

        Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        scene.name = "SketchScape Experience";

        var experienceRoot = new GameObject("SketchScape Authored Experience");
        var controller = experienceRoot.AddComponent<BuiltExperienceController>();
        controller.Configure(envelope.scene.meta.project_id, envelope.scene.meta.revision, envelope.scene.meta.experience.mode);

        CreateEnvironment(experienceRoot.transform, envelope.scene.meta.environment);
        CreateQuestRig(experienceRoot.transform);

        var objectRoot = new GameObject("Authored Objects").transform;
        objectRoot.SetParent(experienceRoot.transform, false);
        var stagedRefs = new List<ImmersiveStagingDirector.StagedObjectRef>();
        foreach (var item in envelope.scene.objects)
        {
            GameObject instance = CreateAuthoredObject(objectRoot, item);
            AttachAttribution(instance, item.id, envelope.scene.meta.social);
            stagedRefs.Add(new ImmersiveStagingDirector.StagedObjectRef { objectId = item.id, target = instance });
        }

        // Build Plan step 6 Part B: stage_immersive_reveal's output, if the
        // compiled scene carries one (meta.staging). Absent entirely, the
        // scene builds and loads exactly as before (graceful degradation).
        if (StagingPlanParser.TryExtractStagingBlock(json, out string stagingBlock))
        {
            experienceRoot.AddComponent<ImmersiveStagingDirector>().Configure(stagingBlock, stagedRefs);
        }

        // Build Plan step 33: the guide bot fetches its own tour at runtime
        // (GET /v1/rooms/{project_id}/guide/tour) and simply doesn't spawn if
        // the project has none -- nothing else to configure here.
        var guideBot = SketchScapeGuideBot.Spawn(experienceRoot.transform);
        experienceRoot.AddComponent<SketchScapeGuideInput>().Configure(guideBot);

        EditorSceneManager.SaveScene(scene, OutputScenePath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(OutputScenePath, true) };
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("Built offline SketchScape experience at " + OutputScenePath);
    }

    private static void CreateEnvironment(Transform parent, OfflineEnvironment environment)
    {
        var environmentRoot = new GameObject("Environment").transform;
        environmentRoot.SetParent(parent, false);

        var lightObject = new GameObject("Experience Key Light");
        lightObject.transform.SetParent(environmentRoot, false);
        lightObject.transform.rotation = Quaternion.Euler(48f, -32f, 0f);
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = environment != null && environment.lighting_preset == "warm_twilight" ? 1.15f : 1f;
        light.color = environment != null && environment.lighting_preset == "warm_twilight"
            ? new Color(1f, 0.72f, 0.52f)
            : Color.white;

        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = new Color(0.22f, 0.29f, 0.42f);
        RenderSettings.ambientEquatorColor = new Color(0.14f, 0.17f, 0.22f);
        RenderSettings.ambientGroundColor = new Color(0.06f, 0.07f, 0.09f);

        if (environment == null || environment.floor)
        {
            var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Walkable Floor";
            floor.transform.SetParent(environmentRoot, false);
            floor.transform.localScale = new Vector3(4f, 1f, 4f);
            // Point a controller at the floor and release the thumbstick to teleport;
            // the starter rig's thumbstick move and snap turn work anywhere.
            var teleportArea = floor.AddComponent<TeleportationArea>();
            teleportArea.interactionLayers = InteractionLayerMask.GetMask(TeleportInteractionLayer);
        }
    }

    private static void CreateQuestRig(Transform parent)
    {
        GameObject rigPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(StarterRigPath);
        if (rigPrefab != null)
        {
            var rig = PrefabUtility.InstantiatePrefab(rigPrefab) as GameObject;
            rig.name = "XR Origin (Quest)";
            rig.transform.SetParent(parent, false);
            EnableSmoothTurn(rig);
            return;
        }

        Debug.LogWarning("XRI Starter Assets are not imported; using the minimal XR rig scaffold.");
        var origin = new GameObject("XR Origin (Quest)");
        origin.transform.SetParent(parent, false);
        AddComponentIfAvailable(origin, "Unity.XR.CoreUtils.XROrigin, Unity.XR.CoreUtils");

        var cameraOffset = new GameObject("Camera Offset");
        cameraOffset.transform.SetParent(origin.transform, false);
        cameraOffset.transform.localPosition = new Vector3(0f, 1.6f, 0f);

        var cameraObject = new GameObject("Main Camera");
        cameraObject.tag = "MainCamera";
        cameraObject.transform.SetParent(cameraOffset.transform, false);
        cameraObject.AddComponent<Camera>();
        cameraObject.AddComponent<AudioListener>();
        cameraObject.AddComponent<TrackedPoseDriver>();

        CreateControllerPlaceholder(cameraOffset.transform, "Left Controller");
        CreateControllerPlaceholder(cameraOffset.transform, "Right Controller");
    }

    /// <summary>
    /// The starter rig snap-turns by default; switch its controllers to smooth
    /// (continuous) turning, with forgiving stick input (EasyTurnInput).
    /// Teleport and thumbstick movement are unchanged. Set by serialized name so
    /// the Editor assembly needn't reference the sample.
    /// </summary>
    private static void EnableSmoothTurn(GameObject rig)
    {
        rig.AddComponent<EasyTurnInput>();
        foreach (var component in rig.GetComponentsInChildren<MonoBehaviour>(true))
        {
            if (component == null || component.GetType().Name != "ControllerInputActionManager")
            {
                continue;
            }
            var serialized = new SerializedObject(component);
            var smoothTurn = serialized.FindProperty("m_SmoothTurnEnabled");
            if (smoothTurn != null)
            {
                smoothTurn.boolValue = true;
                serialized.ApplyModifiedPropertiesWithoutUndo();
            }
        }
    }

    private static void CreateControllerPlaceholder(Transform parent, string name)
    {
        var controller = new GameObject(name);
        controller.transform.SetParent(parent, false);
        AddComponentIfAvailable(controller, "UnityEngine.XR.Interaction.Toolkit.Interactors.XRRayInteractor, Unity.XR.Interaction.Toolkit");
    }

    private static void AttachAttribution(GameObject instance, string objectId, OfflineSocialManifest social)
    {
        if (social == null || social.objects == null)
        {
            return;
        }
        foreach (var entry in social.objects)
        {
            if (entry != null && entry.object_id == objectId)
            {
                instance.AddComponent<ContributorAttribution>().Configure(
                    entry.contribution_id,
                    entry.contributor_id,
                    entry.contributor_display_name,
                    entry.source_type,
                    entry.attribution_color,
                    entry.staging_cue_id);
                return;
            }
        }
    }

    private static GameObject CreateAuthoredObject(Transform parent, SketchSceneObject item)
    {
        if (item.source == "sketch_card")
        {
            return CreateSketchCard(parent, item);
        }

        string localPlyPath = ArtifactFolder + "/" + item.id + ".ply";
        GsplatAsset splatAsset = null;
        if (File.Exists(localPlyPath))
        {
            AssetDatabase.ImportAsset(localPlyPath, ImportAssetOptions.ForceSynchronousImport);
            splatAsset = AssetDatabase.LoadAssetAtPath<GsplatAsset>(localPlyPath);
        }

        GameObject instance;
        if (splatAsset != null)
        {
            instance = new GameObject(item.id);
            var renderer = instance.AddComponent<GsplatRenderer>();
            renderer.GsplatAsset = splatAsset;
            var collider = instance.AddComponent<BoxCollider>();
            collider.center = splatAsset.Bounds.center;
            collider.size = splatAsset.Bounds.size;
        }
        else
        {
            bool tree = item.type != null && item.type.IndexOf("tree", StringComparison.OrdinalIgnoreCase) >= 0;
            bool house = item.type != null && item.type.IndexOf("house", StringComparison.OrdinalIgnoreCase) >= 0;
            if (tree || house)
            {
                instance = GameObject.CreatePrimitive(tree ? PrimitiveType.Capsule : PrimitiveType.Cube);
                instance.name = item.id;
            }
            else
            {
                instance = CreateKeepsakePlaceholder(item.id);
            }
        }
        instance.transform.SetParent(parent, false);
        instance.transform.position = ToVector(item.position, Vector3.zero);
        instance.transform.rotation = Quaternion.Euler(ToVector(item.rotation, Vector3.zero));
        instance.transform.localScale = ToVector(item.scale, Vector3.one);

        var interactive = instance.AddComponent<NamedSceneInteractive>();
        interactive.Configure(item.id, item.type, item.actions);
        if (item.grabbable)
        {
            instance.AddComponent<SketchScapePickup>();
        }
        if (splatAsset == null && !string.IsNullOrWhiteSpace(item.asset_url))
        {
            var marker = instance.AddComponent<AuthoredAssetReference>();
            marker.Configure(item.asset_url, item.source);
            Debug.LogWarning("Missing packaged splat for " + item.id + "; expected " + localPlyPath);
        }
        return instance;
    }

    /// <summary>
    /// Stand-in for a reconstruction whose splat isn't packaged yet: a mug-like
    /// body with a colored handle, so rotation is visible, resting on its pivot
    /// (the floor) rather than half-sunk into it.
    /// </summary>
    private static GameObject CreateKeepsakePlaceholder(string name)
    {
        var root = new GameObject(name);
        var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");

        var body = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        body.name = "Placeholder Body";
        UnityEngine.Object.DestroyImmediate(body.GetComponent<Collider>());
        body.transform.SetParent(root.transform, false);
        body.transform.localPosition = new Vector3(0f, 0.2f, 0f);
        body.transform.localScale = new Vector3(0.3f, 0.2f, 0.3f); // A cylinder primitive is 2 units tall.
        body.GetComponent<Renderer>().sharedMaterial = new Material(shader) { name = "Placeholder Body", color = new Color(0.9f, 0.88f, 0.84f) };

        var handle = GameObject.CreatePrimitive(PrimitiveType.Cube);
        handle.name = "Placeholder Handle";
        UnityEngine.Object.DestroyImmediate(handle.GetComponent<Collider>());
        handle.transform.SetParent(root.transform, false);
        handle.transform.localPosition = new Vector3(0.19f, 0.2f, 0f);
        handle.transform.localScale = new Vector3(0.08f, 0.22f, 0.05f);
        handle.GetComponent<Renderer>().sharedMaterial = new Material(shader) { name = "Placeholder Handle", color = new Color(0.85f, 0.3f, 0.25f) };

        var collider = root.AddComponent<BoxCollider>();
        collider.center = new Vector3(0.03f, 0.2f, 0f);
        collider.size = new Vector3(0.38f, 0.4f, 0.3f);
        return root;
    }

    private static GameObject CreateSketchCard(Transform parent, SketchSceneObject item)
    {
        Texture2D texture = null;
        foreach (string extension in new[] { ".png", ".jpg" })
        {
            string localImagePath = ArtifactFolder + "/" + item.id + extension;
            if (File.Exists(localImagePath))
            {
                AssetDatabase.ImportAsset(localImagePath, ImportAssetOptions.ForceSynchronousImport);
                texture = AssetDatabase.LoadAssetAtPath<Texture2D>(localImagePath);
                break;
            }
        }
        if (texture == null)
        {
            Debug.LogWarning("Missing packaged sketch image for " + item.id + "; expected " + ArtifactFolder + "/" + item.id + ".png");
        }

        GameObject instance = SketchCard.Create(item.id, SketchCard.CreatePageMaterial(texture));
        instance.transform.SetParent(parent, false);
        instance.transform.position = ToVector(item.position, Vector3.zero);
        instance.transform.rotation = Quaternion.Euler(ToVector(item.rotation, Vector3.zero));
        instance.transform.localScale = ToVector(item.scale, Vector3.one);
        instance.AddComponent<NamedSceneInteractive>().Configure(item.id, item.type, item.actions);
        return instance;
    }

    private static void AddComponentIfAvailable(GameObject target, string assemblyQualifiedType)
    {
        Type type = Type.GetType(assemblyQualifiedType);
        if (type != null && typeof(Component).IsAssignableFrom(type) && target.GetComponent(type) == null)
        {
            target.AddComponent(type);
        }
    }

    private static Vector3 ToVector(float[] values, Vector3 fallback)
    {
        return values != null && values.Length >= 3 ? new Vector3(values[0], values[1], values[2]) : fallback;
    }

    private static void EnsureFolder(string path)
    {
        if (AssetDatabase.IsValidFolder(path))
        {
            return;
        }
        string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
        string name = Path.GetFileName(path);
        AssetDatabase.CreateFolder(parent, name);
    }

    [Serializable]
    private sealed class OfflineSceneEnvelope
    {
        public OfflineSceneDocument scene;
    }

    [Serializable]
    private sealed class OfflineSceneDocument
    {
        public SketchSceneObject[] objects;
        public OfflineMeta meta;
    }

    [Serializable]
    private sealed class OfflineMeta
    {
        public string project_id;
        public int revision;
        public OfflineExperience experience;
        public OfflineEnvironment environment;
        public OfflineSocialManifest social;
    }

    [Serializable]
    private sealed class OfflineSocialManifest
    {
        public int version;
        public OfflineAttribution[] objects;
    }

    [Serializable]
    private sealed class OfflineAttribution
    {
        public string object_id;
        public string contribution_id;
        public string contributor_id;
        public string contributor_display_name;
        public string source_type;
        public string attribution_color;
        public string staging_cue_id;
    }

    [Serializable]
    private sealed class OfflineExperience
    {
        public string mode = "vr";
    }

    [Serializable]
    private sealed class OfflineEnvironment
    {
        public string lighting_preset;
        public bool floor = true;
    }
}
