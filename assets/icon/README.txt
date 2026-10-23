ATC tower - two render variants

Open ATC-tower.blend. Choose Tower - Blue Background or Tower - White Background in Blender's Scene selector (top right). Numpad 0 shows the shared camera; F12 renders the selected scene.

To render both: save your Blender changes, then double-click render_both.cmd in this folder. Keep render_both.py and ATC-tower.blend beside it. Outputs are tower-blue-{size}.png and tower-white-{size}.png at 512, 384, 192, and 96 pixels square. The 512px renders are also copied to tower-blue.png and tower-white.png for compatibility. The launcher uses this computer's installed Blender.

Inside Blender, you can also open the Scripting workspace, choose the text 'Render both variants.py', and click Run Script.

Edit the original tower in Tower - Blue Background. Mesh data is shared with the white version; placement follows the original through constraints. Both scenes use the same camera and lights. Materials and visible world backgrounds are independent.

Mesh edits update both variants. Adding/removing objects or changing modifiers requires updating the other variant too. Avoid deleting the original objects: the white objects follow them.

Backgrounds are exact solid sRGB #568ed2 and #ffffff, independent of lighting and camera orientation. Standard color management and disabled dithering preserve these colors.

Rounded corners: both outputs use transparent PNG corners with radius 15% of the shorter side (76.8 pixels at 512 square). The script refreshes the mask for each scene's output dimensions. Saved masks also work with F12 at the current size; rerun the script after changing resolution.

