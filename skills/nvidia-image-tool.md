# NVIDIA Image Tool

Use this when sir asks to generate an image, picture, photo, drawing, or artwork.

Behavior:

- Generate through the configured NVIDIA image model.
- Use `NVIDIA_IMAGE_MODEL` when set; otherwise use the project default.
- Save generated images under an allowed output folder.
- If sir provides an output path, use it only when it is inside allowed local folders.
- Return the saved image path or the exact failure.
