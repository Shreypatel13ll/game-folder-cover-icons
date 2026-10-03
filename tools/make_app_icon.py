"""Generate a simple folder-and-gamepad icon for the Windows manager."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw


def main() -> None:
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((36, 126, 476, 443), radius=58, fill="#18325D")
    draw.rounded_rectangle((56, 91, 250, 183), radius=28, fill="#2374CA")
    draw.rounded_rectangle((54, 151, 458, 421), radius=42, fill="#2D8DEA")
    draw.rounded_rectangle((117, 230, 395, 357), radius=59, fill="#F7FAFF")
    draw.rounded_rectangle((160, 251, 180, 336), radius=7, fill="#1D4F86")
    draw.rounded_rectangle((127, 282, 213, 304), radius=7, fill="#1D4F86")
    draw.ellipse((297, 262, 323, 288), fill="#1D4F86")
    draw.ellipse((338, 298, 364, 324), fill="#1D4F86")
    image.save(destination, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(destination)


if __name__ == "__main__":
    main()
