import bpy
import numpy as np
from pathlib import Path

VARIANTS = [
    ("Tower - Blue Background", "tower-blue.png"),
    ("Tower - White Background", "tower-white.png"),
]
SVG_RADIUS_RATIO = 0.15

def setup_corners(scene):
    w = max(1, int(scene.render.resolution_x * scene.render.resolution_percentage / 100))
    h = max(1, int(scene.render.resolution_y * scene.render.resolution_percentage / 100))
    radius = min(w, h) * SVG_RADIUS_RATIO
    name = f"SVG rounded corner mask {w}x{h} radius={radius!r}"
    mask = bpy.data.images.get(name)
    if mask is None:
        mask = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True)
        # Signed distance to a rounded rectangle, with one-pixel antialiasing.
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        qx = np.abs(x + .5 - w / 2) - (w / 2 - radius)
        qy = np.abs(y + .5 - h / 2) - (h / 2 - radius)
        distance = np.sqrt(np.maximum(qx, 0)**2 + np.maximum(qy, 0)**2) + np.minimum(np.maximum(qx, qy), 0) - radius
        pixels = np.ones((h, w, 4), dtype=np.float32)
        pixels[:, :, 3] = np.clip(.5 - distance, 0, 1)
        mask.pixels.foreach_set(pixels.ravel())
        mask.update()
        mask.pack()
    tree = scene.compositing_node_group
    output = next(n for n in tree.nodes if n.bl_idname == "NodeGroupOutput")
    clip = tree.nodes.get("SVG rounded corners")
    if clip is None:
        original = output.inputs[0].links[0].from_socket
        clip = tree.nodes.new("CompositorNodeSetAlpha")
        clip.name = "SVG rounded corners"
        clip.label = "Rounded corners"
        tree.links.new(original, clip.inputs["Image"])
        tree.links.new(clip.outputs[0], output.inputs[0])
        clip.location = (200, 50)
        output.location = (450, 50)
    image = tree.nodes.get("SVG corner mask")
    if image is None:
        image = tree.nodes.new("CompositorNodeImage")
        image.name = "SVG corner mask"
        image.location = (-50, -200)
    clip.label = f"Corner radius: {radius:.4f}px"
    image.image = mask
    tree.links.new(image.outputs["Alpha"], clip.inputs["Alpha"])
    settings = scene.render.image_settings
    settings.file_format = next(i.identifier for i in settings.bl_rna.properties["file_format"].enum_items if i.identifier == "PNG")
    settings.color_mode = next(i.identifier for i in settings.bl_rna.properties["color_mode"].enum_items if i.identifier == "RGBA")
    scene["Corner radius pixels"] = radius
    print(f"{scene.name}: {w}x{h}, radius {radius:.4f}px")

def render_both():
    folder = Path(bpy.data.filepath).parent
    original_scene = bpy.context.window.scene if bpy.context.window else None
    try:
        for scene_name, filename in VARIANTS:
            scene = bpy.data.scenes[scene_name]
            setup_corners(scene)
            scene.render.filepath = str(folder / filename)
            bpy.ops.render.render(scene=scene.name, write_still=True)
            print("Saved:", scene.render.filepath)
    finally:
        if original_scene and bpy.context.window:
            bpy.context.window.scene = original_scene

if __name__ == "__main__":
    render_both()
