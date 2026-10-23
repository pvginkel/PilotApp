import bpy
import numpy as np
from pathlib import Path

VARIANTS = [
    # Scene, output stem, and whether a maskable icon is made from it.
    ("Tower - Blue Background", "tower-blue", True),
    ("Tower - White Background", "tower-white", False),
]
RENDER_SIZES = (512, 384, 192, 96)
SVG_RADIUS_RATIO = 0.15
# The maskable icon is the tile full-bleed with the tower at 0.8 of its size, inside the 80% safe
# circle a launcher may clip to.
MASKABLE_SIZE = 512
MASKABLE_SCALE = 0.8

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

def write_maskable(scene, folder, stem):
    """Renders the tile at 0.8 of the maskable size and centres it on a canvas of the tile's blue."""
    inner = round(MASKABLE_SIZE * MASKABLE_SCALE)
    render = scene.render
    render.resolution_x = render.resolution_y = inner
    render.resolution_percentage = 100
    setup_corners(scene)
    path = folder / f"{stem}-{MASKABLE_SIZE}-maskable.png"
    render.filepath = str(path)
    bpy.ops.render.render(scene=scene.name, write_still=True)
    tile = bpy.data.images.load(str(path))
    try:
        pixels = np.empty(inner * inner * 4, dtype=np.float32)
        tile.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(tile)
    pixels = pixels.reshape(inner, inner, 4)
    # The tile's own blue, from the middle of its edge, so the fill meets it without a seam; its
    # rounded corners, laid over that blue, vanish into it.
    blue = pixels[0, inner // 2, :3].copy()
    canvas = np.empty((MASKABLE_SIZE, MASKABLE_SIZE, 4), dtype=np.float32)
    canvas[:, :, :3] = blue
    canvas[:, :, 3] = 1
    offset = (MASKABLE_SIZE - inner) // 2
    alpha = pixels[:, :, 3:]
    canvas[offset:offset + inner, offset:offset + inner, :3] = pixels[:, :, :3] * alpha + blue * (1 - alpha)
    image = bpy.data.images.new("Maskable icon", width=MASKABLE_SIZE, height=MASKABLE_SIZE, alpha=True)
    try:
        image.pixels.foreach_set(canvas.ravel())
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)
    print("Saved:", path)

def render_both():
    folder = Path(bpy.data.filepath).parent
    original_scene = bpy.context.window.scene if bpy.context.window else None
    for scene_name, stem, maskable in VARIANTS:
        scene = bpy.data.scenes[scene_name]
        render = scene.render
        original = (render.resolution_x, render.resolution_y,
                    render.resolution_percentage, render.filepath)
        try:
            for size in RENDER_SIZES:
                render.resolution_x = render.resolution_y = size
                render.resolution_percentage = 100
                setup_corners(scene)
                render.filepath = str(folder / f"{stem}-{size}.png")
                bpy.ops.render.render(scene=scene.name, write_still=True)
                print("Saved:", render.filepath)
            if maskable:
                write_maskable(scene, folder, stem)
        finally:
            (render.resolution_x, render.resolution_y,
             render.resolution_percentage, render.filepath) = original
            setup_corners(scene)
            if original_scene and bpy.context.window:
                bpy.context.window.scene = original_scene

if __name__ == "__main__":
    render_both()
