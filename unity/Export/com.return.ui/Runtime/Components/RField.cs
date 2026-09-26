using System;
using Return.Design;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Return.UI
{
    /// <summary>Port of the web Field: label, input, hint, error. Optional submit arrow. Uses TMP_InputField (system keyboard on Quest).</summary>
    public class RField : MonoBehaviour
    {
        public TMP_InputField input;
        public event Action<string> Submitted;
        TextMeshProUGUI _hint, _error; RectTransform _errorRow;
        Image _edge; bool _focused, _hasError; string _hintText;

        public string Text { get => input.text; set => input.text = value; }

        public static RField Create(Transform parent, string label = null, string placeholder = "", string hint = null, bool multiline = false,
            bool password = false, bool onImage = false, string submitLabel = null, string initial = "", int maxLength = 0)
        {
            var root = UI.V(parent, "Field", 8);
            var f = root.gameObject.AddComponent<RField>();
            if (label != null) UI.Text(root, label, TextStyle.Label, onImage ? ColorRole.OnImage : ColorRole.Ink);

            float h = multiline ? 132 : 56;
            var box = UI.Box(root, "Input"); UI.Size(box, -1, h);
            var bg = UI.Bg(box, onImage ? ColorRole.GlassStrong : ColorRole.Surface200, 20);
            bg.raycastTarget = true;
            f._edge = UI.Border(box, onImage ? ColorRole.GlassEdge : ColorRole.LineStrong, 20, 2);

            var area = UI.Box(box, "TextArea"); UI.Stretch(area, 20, 8, submitLabel != null ? 64 : 20, 8); area.gameObject.AddComponent<RectMask2D>();
            var ph = UI.Text(area, placeholder, TextStyle.Body, ColorRole.InkFaint, multiline ? TextAlignmentOptions.TopLeft : TextAlignmentOptions.Left, multiline);
            var tx = UI.Text(area, "", TextStyle.Body, ColorRole.Ink, multiline ? TextAlignmentOptions.TopLeft : TextAlignmentOptions.Left, multiline);
            UI.Stretch(ph.rectTransform); UI.Stretch(tx.rectTransform);
            tx.overflowMode = TextOverflowModes.Overflow;

            var inp = box.gameObject.AddComponent<TMP_InputField>();
            inp.textViewport = area; inp.textComponent = tx; inp.placeholder = ph;
            inp.lineType = multiline ? TMP_InputField.LineType.MultiLineNewline : TMP_InputField.LineType.SingleLine;
            inp.contentType = password ? TMP_InputField.ContentType.Password : TMP_InputField.ContentType.Standard;
            inp.characterLimit = maxLength; inp.customCaretColor = true; inp.caretColor = new Color32(47, 95, 168, 255);
            inp.selectionColor = new Color32(47, 95, 168, 90); inp.caretWidth = 3;
            inp.text = initial;
            f.input = inp;
            inp.onSelect.AddListener(_ => { f._focused = true; f.RefreshEdge(); });
            inp.onDeselect.AddListener(_ => { f._focused = false; f.RefreshEdge(); });
            if (!multiline) inp.onSubmit.AddListener(v => f.Submitted?.Invoke(v));

            if (submitLabel != null)
            {
                var b = UI.Img(box, "Submit", ColorRole.Action, Shapes.Pill, Image.Type.Sliced, true);
                UI.Anchor(b.rectTransform, new Vector2(1, 0.5f), new Vector2(-8, 0), new Vector2(40, 40)); b.rectTransform.pivot = new Vector2(1, 0.5f);
                UI.Icon(b.rectTransform, "arrowRight", ColorRole.OnAction, 20).rectTransform.anchoredPosition = Vector2.zero;
                var p = b.gameObject.AddComponent<Pressable>(); p.onClick = () => f.Submitted?.Invoke(inp.text);
            }

            f._hintText = hint;
            if (hint != null) f._hint = UI.Text(root, hint, TextStyle.Caption, onImage ? ColorRole.OnImage : ColorRole.InkMuted);
            f._errorRow = UI.H(root, "Error", 6); f._errorRow.gameObject.SetActive(false);
            UI.Icon(f._errorRow, "alert", ColorRole.Danger, 16);
            f._error = UI.Text(f._errorRow, "", TextStyle.Caption, ColorRole.Danger);
            return f;
        }

        void RefreshEdge()
        {
            UI.SetRole(_edge, _hasError ? ColorRole.Danger : _focused ? ColorRole.Focus : ColorRole.LineStrong);
        }

        public void SetError(string message)
        {
            _hasError = !string.IsNullOrEmpty(message);
            _errorRow.gameObject.SetActive(_hasError);
            _error.text = message ?? "";
            if (_hint != null) _hint.gameObject.SetActive(!_hasError);
            RefreshEdge();
        }

        public void Clear() { input.text = ""; SetError(null); }
    }
}
