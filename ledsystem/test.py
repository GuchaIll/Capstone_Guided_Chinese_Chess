import board
import neopixel

# LED setup
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

BOARD_LED_MAP = [
    [3,   6,   9,  12,  15,  18,  21,  24,  27],
    [61, 58,  55,  52,  49,  46,  43,  40,  37],
    [73, 76,  79,  82,  85,  88,  91,  94,  97],
    [146, 143, 140, 137, 134, 131, 128, 125, 122],
    [158, 161, 164, 167, 170, 173, 176, 179, 182],
    [216, 213, 210, 207, 204, 201, 198, 195, 192],
    [227, 230, 233, 236, 239, 242, 245, 248, 251],
    [286, 283, 280, 277, 274, 271, 268, 265, 262],
    [298, 301, 304, 307, 310, 313, 316, 319, 322],
    [359, 356, 353, 350, 347, 344, 341, 338, 335],
]

WHITE = (0, 0, 0, 255)
OFF = (0, 0, 0, 0)

def clear():
    pixels.fill(OFF)
    pixels.show()

def walk_manual():
    print("\nManual LED walker")
    print("Press ENTER or 'n' → next")
    print("Press 'q' → quit\n")

    for r in range(len(BOARD_LED_MAP)):
        for c in range(len(BOARD_LED_MAP[0])):
            led_idx = BOARD_LED_MAP[r][c]

            clear()
            pixels[led_idx] = WHITE
            pixels.show()

            print(f"Row {r}, Col {c} → LED {led_idx}")

            user = input("> ").strip().lower()

            if user == "q":
                clear()
                print("Exiting.")
                return
            # Enter OR 'n' both just continue

    clear()
    print("\nDone.\n")

if __name__ == "__main__":
    clear()
    walk_manual()
