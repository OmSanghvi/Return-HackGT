// SketchScape SharedLetterPage — the opened letter: a paper page that unfolds out of its envelope
// and stands on a little wire stand above the letters desk, showing the letter's page texture
// (texture_url, or the snapshot PNG offline) or its body text.
// Canonical source: Return-HackGT/unity-hackgt/ (see scripts/install_hackgt_roomkit.py).
// Built by SharedRoomLayer; Update only runs the unfold/fold animation and allocates nothing.
using TMPro;
using UnityEngine;

namespace SketchScape
{
    public class SharedLetterPage : MonoBehaviour
    {
        public Transform sheet;            // animated: scaled/rotated/moved out of the envelope
        public Transform paper;            // backing box (w x h)
        public MeshRenderer picture;       // textured quad
        public TextMeshPro title;
        public TextMeshPro bodyText;
        public GameObject stand;
        public float width = 0.42f;
        public float unfoldSeconds = 0.9f;

        public string CurrentLetter { get; private set; }
        public bool Visible { get { return sheet != null && sheet.gameObject.activeSelf && _target > 0.5f; } }
        public bool ShowsTexture { get; private set; }

        Material _pictureMat;
        Vector3 _fromPos, _restPos;
        Quaternion _fromRot, _restRot;
        float _t, _target;


        void Awake()
        {
            if (sheet != null)
            {
                _restPos = sheet.localPosition;
                _restRot = sheet.localRotation;
                if (_target <= 0f) sheet.gameObject.SetActive(false);
            }
            if (stand != null && _target <= 0f) stand.SetActive(false);
        }

        /// <summary>Unfold the page for a letter out of the given envelope. Content comes via SetTexture / SetBody.</summary>
        public void Show(string letterId, string heading, Transform fromEnvelope)
        {
            if (sheet == null) return;
            CurrentLetter = letterId;
            if (title != null) title.text = heading ?? "";
            if (fromEnvelope != null && sheet.parent != null)
            {
                _fromPos = sheet.parent.InverseTransformPoint(fromEnvelope.position);
                _fromRot = Quaternion.Inverse(sheet.parent.rotation) * fromEnvelope.rotation;
            }
            else { _fromPos = _restPos + new Vector3(0f, -0.25f, -0.1f); _fromRot = _restRot * Quaternion.Euler(80f, 0f, 0f); }
            SetBody("Opening...");
            _t = 0f;
            _target = 1f;
            sheet.gameObject.SetActive(true);
            if (stand != null) stand.SetActive(false);
            Pose(0f);
        }

        public void Hide()
        {
            _target = 0f;
            if (stand != null) stand.SetActive(false);
        }

        public void SetTexture(Texture2D tex)
        {
            if (picture == null || tex == null) return;
            if (_pictureMat == null)
            {
                _pictureMat = new Material(picture.sharedMaterial) { name = "Letter Page (runtime)" };
                picture.sharedMaterial = _pictureMat;
            }
            _pictureMat.mainTexture = tex;
            float aspect = tex.height / Mathf.Max(1f, (float)tex.width);
            Resize(Mathf.Clamp(width * aspect, 0.24f, 0.6f));
            picture.gameObject.SetActive(true);
            if (bodyText != null) bodyText.gameObject.SetActive(false);
            ShowsTexture = true;
        }

        public void SetBody(string text)
        {
            if (picture != null) picture.gameObject.SetActive(false);
            if (bodyText != null) { bodyText.gameObject.SetActive(true); bodyText.text = text ?? ""; }
            Resize(0.5f);
            ShowsTexture = false;
        }

        void Resize(float h)
        {

            float top = 0.052f;
            if (paper != null)
            {
                paper.localScale = new Vector3(width, h + top, 0.003f);
                paper.localPosition = new Vector3(0f, top / 2f, 0.0015f);
            }
            if (picture != null)
            {
                picture.transform.localScale = new Vector3(width - 0.024f, h - 0.024f, 1f);
                picture.transform.localPosition = new Vector3(0f, 0f, -0.0008f);
            }
            if (bodyText != null)
            {
                bodyText.rectTransform.sizeDelta = new Vector2(width - 0.05f, h - 0.04f);
                bodyText.transform.localPosition = new Vector3(0f, 0f, -0.0015f);
            }
            if (title != null)
            {
                title.rectTransform.sizeDelta = new Vector2(width - 0.04f, top - 0.01f);
                title.transform.localPosition = new Vector3(0f, h / 2f + top / 2f, -0.0015f);
            }
        }

        void Pose(float t)
        {
            float e1 = Ease(Mathf.Clamp01(t / 0.45f));
            float e2 = Ease(Mathf.Clamp01((t - 0.3f) / 0.7f));
            sheet.localPosition = Vector3.LerpUnclamped(_fromPos, _restPos, e1);
            sheet.localRotation = Quaternion.SlerpUnclamped(_fromRot, _restRot, e1);
            sheet.localScale = new Vector3(Mathf.Lerp(0.45f, 1f, e1), Mathf.Lerp(0.12f, 1f, e2), 1f);
        }

        static float Ease(float x) { return 1f - (1f - x) * (1f - x) * (1f - x); }

        void Update()
        {
            if (sheet == null || !sheet.gameObject.activeSelf) return;
            if (Mathf.Abs(_t - _target) < 0.0001f) return;
            _t = Mathf.MoveTowards(_t, _target, Time.unscaledDeltaTime / Mathf.Max(0.1f, unfoldSeconds));
            Pose(_t);
            if (_t >= 1f && stand != null && !stand.activeSelf) stand.SetActive(true);
            if (_t <= 0f) { sheet.gameObject.SetActive(false); CurrentLetter = null; }
        }

        void OnDestroy()
        {
            if (_pictureMat != null && Application.isPlaying) Destroy(_pictureMat);
        }
    }
}
