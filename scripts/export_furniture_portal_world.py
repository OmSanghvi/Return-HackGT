"""Export a small curated living-room world from Furniture_FREE.blend.

Run through Blender in background mode. It changes objects only in Blender's
temporary session and writes one Unity-ready FBX; it never saves over the
source .blend.
"""

from __future__ import annotations

from pathlib import Path

import bpy


OUTPUT = Path("/Users/shruti/HackGTUnity/Assets/Resources/Furniture/FurniturePortalWorld.fbx")

# Source-object name -> composed living-room location + Z-axis rotation.
LAYOUT = {
    "SM_Sofa_41": ((0.0, 3.3, 0.0), 0.0),
    "SM_Coffe_Table_2": ((0.0, 1.55, 0.0), 0.0),
    "SM_Chair_13": ((-2.15, 1.45, 0.0), -0.45),
    "SM_Chair_28": ((2.15, 1.45, 0.0), 0.45),
    "SM_lamp_21": ((-3.1, 3.0, 0.0), 0.0),
    "SM_Pots_of_plant_9": ((3.0, 3.15, 0.0), 0.0),
    "SM_picture_3": ((0.0, 4.25, 1.05), 0.0),
    "SM_Commode_7": ((3.15, 4.25, 0.0), 0.0),
    "SM_lamp_5": ((-2.7, 0.2, 0.0), 0.0),
    "SM_Fruit_Bowl": ((0.0, 1.55, 0.53), 0.0),
}


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    selected = []
    for name, (position, rotation_z) in LAYOUT.items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise RuntimeError(f"Furniture source is missing expected object: {name}")
        obj.location = position
        obj.rotation_euler = (0.0, 0.0, rotation_z)
        obj.select_set(True)
        selected.append(obj)

    bpy.context.view_layer.objects.active = selected[0]
    bpy.ops.export_scene.fbx(
        filepath=str(OUTPUT),
        use_selection=True,
        object_types={"MESH"},
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        axis_forward="-Z",
        axis_up="Y",
        apply_unit_scale=True,
        path_mode="AUTO",
        embed_textures=False,
    )
    print(f"Exported {len(selected)} furniture objects to {OUTPUT}")


main()
