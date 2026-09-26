using System;
using UnityEngine;
using UnityEngine.EventSystems;

namespace Return.UI
{
    /// <summary>Click target with hover/press feedback (Fast motion). Works with any EventSystem ray, poke or mouse.</summary>
    [RequireComponent(typeof(RectTransform))]
    public class Pressable : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler, IPointerDownHandler, IPointerUpHandler, IPointerClickHandler
    {
        public Action onClick;
        public bool interactable = true;
        public float hoverScale = 1.02f, pressScale = 0.97f;
        bool _hover, _down;
        CanvasGroup _cg;

        public bool Hover => _hover;

        void Awake() { _cg = this.GetOrAdd<CanvasGroup>(); }

        void Update()
        {
            float target = !interactable ? 1f : _down ? pressScale : _hover ? hoverScale : 1f;
            float k = 1f - Mathf.Exp(-Design.ReturnMotion.Fast * 90f * Time.unscaledDeltaTime);
            transform.localScale = Vector3.Lerp(transform.localScale, Vector3.one * target, k);
            if (_cg != null) _cg.alpha = interactable ? 1f : 0.45f;
        }

        void OnDisable() { _hover = _down = false; transform.localScale = Vector3.one; }

        public void OnPointerEnter(PointerEventData e) { _hover = true; }
        public void OnPointerExit(PointerEventData e) { _hover = false; _down = false; }
        public void OnPointerDown(PointerEventData e) { _down = true; }
        public void OnPointerUp(PointerEventData e) { _down = false; }
        public void OnPointerClick(PointerEventData e) { if (interactable) onClick?.Invoke(); }
    }

    /// <summary>Continuous rotation for the spinner icon.</summary>
    public class Spin : MonoBehaviour
    {
        public float degPerSec = -280f;
        void Update() { transform.Rotate(0, 0, degPerSec * Time.unscaledDeltaTime); }
    }
}
