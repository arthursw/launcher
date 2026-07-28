"""Regression tests for packaged launcher artwork."""

from pathlib import Path

from PIL import Image

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


def test_default_png_icon_has_normalized_transparent_inset():
    """The portable icon should not fill the complete application-icon canvas."""
    with Image.open(ASSETS_DIR / "launcher.png") as icon:
        rgba = icon.convert("RGBA")

    assert rgba.size == (512, 512)
    assert rgba.getchannel("A").getbbox() == (32, 32, 480, 480)


def test_default_icns_icon_contains_standard_and_retina_representations():
    """The macOS icon should include both standard and high-resolution artwork."""
    with Image.open(ASSETS_DIR / "app.icns") as icon:
        sizes = set(icon.info["sizes"])

    assert (128, 128, 1) in sizes
    assert (256, 256, 1) in sizes
    assert (512, 512, 1) in sizes
    assert (512, 512, 2) in sizes
