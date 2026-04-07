import serial
import time
import datetime
import argparse


def calculate_checksum(sentence):
    """Calculate the NMEA checksum."""
    checksum = 0
    for char in sentence:
        checksum ^= ord(char)
    return f"{checksum:02X}"


def format_gprmc(lat, lon, lat_dir, lon_dir):
    """Format a basic GPRMC sentence."""
    now = datetime.datetime.now(datetime.timezone.utc)
    time_str = now.strftime("%H%M%S.00")
    date_str = now.strftime("%d%m%y")

    # speed and course arbitrarily set to 0.0
    # format: $GPRMC,TIME,A,LAT,LAT_DIR,LON,LON_DIR,SPD,CRS,DATE,,,A*CS
    core_sentence = (
        f"GPRMC,{time_str},A,{lat},{lat_dir},{lon},{lon_dir},0.0,0.0,{date_str},,,A"
    )
    checksum = calculate_checksum(core_sentence)
    return f"${core_sentence}*{checksum}\r\n"


# Triangle points (Lat, Lon arrays or strings that represent NMEA formats)
# For NMEA format:
# DDMM.MMMMM
# Point 1: 40°00.0000' N, 100°00.0000' W
# Point 2: 40°01.0000' N, 100°00.0000' W
# Point 3: 40°00.5000' N, 100°01.0000' W (Creating an approximate triangle)
POINTS = [
    ("4000.0000", "N", "10000.0000", "W"),
    ("4001.0000", "N", "10000.0000", "W"),
    ("4000.5000", "N", "10001.0000", "W"),
]


def main():
    parser = argparse.ArgumentParser(
        description="Simulate a GPS device transmitting NMEA sentences over a COM port."
    )
    parser.add_argument(
        "--port",
        type=str,
        required=True,
        help="COM port to write to (e.g., COM3, /dev/ttyUSB0)",
    )
    parser.add_argument(
        "--baud", type=int, default=9600, help="Baud rate (default: 9600)"
    )
    args = parser.parse_args()

    try:
        # Note: on Windows, if you want another application to read from this,
        # you typically need a virtual COM port pair (like com0com).
        # Write to one end (e.g. COM3), read from the other (e.g. COM4).
        ser = serial.Serial(args.port, args.baud)
        print(f"Opened simulated GPS output on {args.port} at {args.baud} baud")
    except Exception as e:
        print(f"Failed to open {args.port}: {e}")
        return

    point_idx = 0
    count_at_point = 0

    try:
        while True:
            lat, lat_dir, lon, lon_dir = POINTS[point_idx]
            sentence = format_gprmc(lat, lon, lat_dir, lon_dir)

            # Write to serial port
            ser.write(sentence.encode("ascii"))
            print(f"Sent ({count_at_point + 1}/3): {sentence.strip()}")

            count_at_point += 1
            if count_at_point >= 3:
                # Move to next point every 3 seconds (since we run at ~1Hz)
                point_idx = (point_idx + 1) % len(POINTS)
                count_at_point = 0
                print(f"--- Moving to point {point_idx + 1} ---")

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping simulated GPS...")
    finally:
        if "ser" in locals() and ser.is_open:
            ser.close()


if __name__ == "__main__":
    main()
