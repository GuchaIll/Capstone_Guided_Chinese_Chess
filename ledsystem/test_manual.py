import board
import neopixel

PIXEL_PIN = board.D18
NUM_PIXELS = 400
ORDER = neopixel.GRBW

pixels = neopixel.NeoPixel(
    PIXEL_PIN,
    NUM_PIXELS,
    brightness=0.25,
    auto_write=False,
    pixel_order=ORDER
)

COLORS = {
    "off":    (0, 0, 0, 0),
    "white":  (0, 0, 0, 255),
    "red":    (255, 0, 0, 0),
    "green":  (0, 255, 0, 0),
    "blue":   (0, 0, 255, 0),
    "orange": (255, 80, 0, 0),
    "purple": (180, 0, 255, 0),
    "cyan":   (0, 255, 255, 0),
    "yellow": (255, 255, 0, 0),
    "pink":   (255, 0, 120, 0),
}

def clear():
    pixels.fill(COLORS["off"])
    pixels.show()

def set_led(index: int, color_name: str):
    if not (0 <= index < NUM_PIXELS):
        print(f"Index out of range. Valid range: 0 to {NUM_PIXELS - 1}")
        return

    if color_name not in COLORS:
        print(f"Unknown color '{color_name}'. Options: {', '.join(COLORS.keys())}")
        return

    pixels[index] = COLORS[color_name]
    pixels.show()
    print(f"Set LED {index} to {color_name}")

def main():
    clear()
    print("Manual LED tester")
    print("Commands:")
    print("  set <index> <color>   e.g. set 61 white")
    print("  off <index>           e.g. off 61")
    print("  clear")
    print("  colors")
    print("  q")

    while True:
        cmd = input("> ").strip().lower()

        if cmd == "q":
            clear()
            print("Exiting.")
            break

        if cmd == "clear":
            clear()
            print("Cleared all LEDs")
            continue

        if cmd == "colors":
            print("Available colors:", ", ".join(COLORS.keys()))
            continue

        parts = cmd.split()

        if len(parts) == 3 and parts[0] == "set":
            try:
                idx = int(parts[1])
            except ValueError:
                print("Index must be an integer")
                continue

            color = parts[2]
            set_led(idx, color)
            continue

        if len(parts) == 2 and parts[0] == "off":
            try:
                idx = int(parts[1])
            except ValueError:
                print("Index must be an integer")
                continue

            set_led(idx, "off")
            continue

        print("Invalid command")

if __name__ == "__main__":
    main()
