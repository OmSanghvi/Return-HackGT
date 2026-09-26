---
name: sketchscape-subject-labeler
description: Identify the objects in a contributor's uploaded photo (identify_subject) as short noun phrases SAM 3.1 can segment, e.g. "brown tabby cat". Also names the single object marked by a mask. Use when asked what is in a photo, to label or suggest objects for an upload, or to name a reconstructed scan from its mask.
---

# identify_subject

This tool looks at a photo with NemoClaw's configured vision model (Muse
Spark) through the sandbox's managed inference route. Run it with your
shell/exec tool:

```
python3 {baseDir}/backend/nemoclaw_vision.py <photo> [--max 8]
python3 {baseDir}/backend/nemoclaw_vision.py <photo> --mask <mask.png>
```

It prints one JSON line: `{"labels": [...], "backend": "nemoclaw:muse-spark-1.3"}`.

- Without `--mask`, it returns every distinct keepsake object, most
  prominent first, capped at `--max`.
- With `--mask` (a black-and-white image; white marks one object), it
  returns a single label for that object.
- Labels are always a noun plus one or two attributes. They never describe
  positions or relations (SAM 3.1 can't use relational phrases), and generic
  words like "object" are dropped.
- An empty list means nothing clear was found. Say so; never make up a
  label.
- A label a person typed always wins over these suggestions.

The SketchScape backend also calls this script directly
(`SKETCHSCAPE_SUBJECT_LABELER=nemoclaw`) to label uploads that have no typed
name, and for its "Suggest objects" button.
