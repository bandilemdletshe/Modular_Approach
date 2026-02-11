# windows_streamer_tcp.py
import socket
import time
import pyautogui
from PIL import Image
import io
import struct


class WindowsStreamerTCP:
    def __init__(self, target_ip, port=5000):
        self.target_ip = target_ip
        self.port = port
        self.socket = None
        self.running = False

    def connect(self):
        """Establish a TCP connection to the receiver."""
        while True:
            try:
                print(f"Connecting to {self.target_ip}:{self.port} ...")
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.target_ip, self.port))
                print("✅ Connected to receiver.")
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                break
            except Exception as e:
                print(f"⚠️ Connection failed: {e}. Retrying in 3s...")
                time.sleep(3)

    def capture_and_compress(self, quality=70):
        """Capture screen and compress to JPEG using Pillow"""
        try:
            screenshot = pyautogui.screenshot()
            screenshot = screenshot.resize((1024, 600), Image.LANCZOS)
            jpeg_data = io.BytesIO()
            screenshot.save(jpeg_data, format="JPEG", quality=quality, optimize=True)
            return jpeg_data.getvalue()
        except Exception as e:
            print(f"Capture/compression error: {e}")
            return None

    def send_frame(self, jpeg_data):
        """Send frame with TCP and include frame size header."""
        try:
            # 4-byte length prefix before data
            header = struct.pack("!I", len(jpeg_data))
            self.socket.sendall(header + jpeg_data)
        except (BrokenPipeError, ConnectionResetError):
            print("⚠️ Connection lost. Reconnecting...")
            self.connect()
        except Exception as e:
            print(f"Send error: {e}")

    def start_streaming(self, fps=8):
        """Start TCP streaming"""
        self.running = True
        self.connect()

        frame_interval = 1.0 / fps
        frame_count = 0
        start_time = time.time()

        print(f"🎥 Streaming over TCP at {fps} FPS")
        print("Press Ctrl+C to stop")

        try:
            while self.running:
                frame_start = time.time()
                jpeg_data = self.capture_and_compress()

                if jpeg_data:
                    self.send_frame(jpeg_data)
                    frame_count += 1

                    # Show FPS stats
                    current_time = time.time()
                    if current_time - start_time >= 1.0:
                        current_fps = frame_count / (current_time - start_time)
                        print(
                            f"FPS: {current_fps:.1f}, Frame size: {len(jpeg_data)} bytes",
                            end="\r",
                        )
                        frame_count = 0
                        start_time = current_time

                # Maintain frame rate
                elapsed = time.time() - frame_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\nStopping streamer...")
        finally:
            if self.socket:
                self.socket.close()
            self.running = False


if __name__ == "__main__":
    TARGET_IP = "192.168.0.237"  # Replace with your VM or DWIN IP
    streamer = WindowsStreamerTCP(TARGET_IP)
    streamer.start_streaming(fps=8)
