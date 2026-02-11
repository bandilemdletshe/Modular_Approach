import socket
import time
import pyautogui
import pyaudio
import struct
import threading
import sys
from PIL import Image
import io
import numpy as np

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("⚠️ sounddevice not available, falling back to PyAudio")


class VideoStreamer:
    def __init__(self, target_ip, port=5000):
        self.target_ip = target_ip
        self.port = port
        self.socket = None
        self.running = False

    def connect(self):
        """Establish a TCP connection for video."""
        while True:
            try:
                print(f"🎥 Connecting video to {self.target_ip}:{self.port}...")
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.target_ip, self.port))
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print("✅ Video connected to receiver.")
                break
            except Exception as e:
                print(f"⚠️ Video connection failed: {e}. Retrying in 3s...")
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
            print(f"🎥 Capture/compression error: {e}")
            return None

    def send_frame(self, jpeg_data):
        """Send frame with TCP and include frame size header."""
        try:
            header = struct.pack("!I", len(jpeg_data))
            self.socket.sendall(header + jpeg_data)
        except (BrokenPipeError, ConnectionResetError):
            print("⚠️ Video connection lost. Reconnecting...")
            self.connect()
        except Exception as e:
            print(f"🎥 Send error: {e}")

    def start_streaming(self, fps=8):
        """Start video streaming"""
        self.running = True
        self.connect()

        frame_interval = 1.0 / fps
        frame_count = 0
        start_time = time.time()

        print(f"🎥 Streaming video at {fps} FPS")

        try:
            while self.running:
                frame_start = time.time()
                jpeg_data = self.capture_and_compress()

                if jpeg_data:
                    self.send_frame(jpeg_data)
                    frame_count += 1

                    current_time = time.time()
                    if current_time - start_time >= 1.0:
                        current_fps = frame_count / (current_time - start_time)
                        print(f"🎥 FPS: {current_fps:.1f}, Frame size: {len(jpeg_data)} bytes")
                        frame_count = 0
                        start_time = current_time

                elapsed = time.time() - frame_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n🎥 Stopping video streamer...")
        finally:
            if self.socket:
                self.socket.close()
            self.running = False

    def stop_streaming(self):
        """Stop video streaming"""
        self.running = False


class AudioStreamer:
    def __init__(self, target_ip, port=5001):
        self.target_ip = target_ip
        self.port = port
        self.socket = None
        self.running = False

        self.SAMPLE_RATE = 44100
        self.CHANNELS = 2
        self.CHUNK = 1024

    def connect(self):
        """Establish a TCP connection for audio."""
        while True:
            try:
                print(f"🎧 Connecting audio to {self.target_ip}:{self.port}...")
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.target_ip, self.port))
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print("✅ Audio connected to receiver.")
                break
            except Exception as e:
                print(f"⚠️ Audio connection failed: {e}. Retrying in 3s...")
                time.sleep(3)

    def _send_aligned_audio(self, audio_data: bytes):
        """Send audio data ensuring it is aligned to full frames."""
        frame_size = self.CHANNELS * 2  # 2 bytes per sample for 16-bit PCM
        if len(audio_data) % frame_size != 0:
            audio_data = audio_data[:-(len(audio_data) % frame_size)]
        if not audio_data:
            return
        header = struct.pack("!I", len(audio_data))
        try:
            self.socket.sendall(header + audio_data)
        except (BrokenPipeError, ConnectionResetError):
            print("⚠️ Audio connection lost. Reconnecting...")
            self.connect()
        except Exception as e:
            print(f"🎧 Send error: {e}")

    def find_desktop_audio_device_pyaudio(self):
        audio = pyaudio.PyAudio()
        desktop_audio_keywords = [
            "stereo mix", "what you hear", "waveout mix", "loopback",
            "virtual cable", "cable input", "stereo", "mix"
        ]
        for i in range(audio.get_device_count()):
            try:
                info = audio.get_device_info_by_index(i)
                device_name = info['name'].lower()
                if info['maxInputChannels'] > 0:
                    for keyword in desktop_audio_keywords:
                        if keyword in device_name:
                            try:
                                test_stream = audio.open(
                                    format=pyaudio.paInt16,
                                    channels=min(2, info['maxInputChannels']),
                                    rate=self.SAMPLE_RATE,
                                    input=True,
                                    input_device_index=i,
                                    frames_per_buffer=self.CHUNK
                                )
                                test_stream.stop_stream()
                                test_stream.close()
                                audio.terminate()
                                return i, min(2, info['maxInputChannels'])
                            except:
                                continue
            except:
                continue
        audio.terminate()
        return None, 2

    def setup_pyaudio_desktop_capture(self):
        try:
            self.audio = pyaudio.PyAudio()
            device_index, channels = self.find_desktop_audio_device_pyaudio()
            if device_index is None:
                print("❌ No desktop audio capture device found with PyAudio!")
                return None
            stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=self.SAMPLE_RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.CHUNK,
                start=False
            )
            stream.start_stream()
            return stream
        except Exception as e:
            print(f"❌ PyAudio setup error: {e}")
            if hasattr(self, 'audio'):
                self.audio.terminate()
            return None

    def start_streaming(self):
        self.running = True
        self.connect()
        stream = self.setup_pyaudio_desktop_capture()
        if not stream:
            self._cleanup()
            return
        try:
            while self.running:
                audio_data = stream.read(self.CHUNK, exception_on_overflow=False)
                self._send_aligned_audio(audio_data)
        except KeyboardInterrupt:
            print("\n🎧 Stopping audio streamer...")
        finally:
            self._cleanup()

    def _cleanup(self):
        if hasattr(self, 'stream') and self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        if hasattr(self, 'audio') and self.audio:
            try:
                self.audio.terminate()
            except:
                pass
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("🛑 Audio streaming stopped.")

    def stop_streaming(self):
        self.running = False


class AVStreamer:
    def __init__(self, target_ip, video_port=5000, audio_port=5001):
        self.target_ip = target_ip
        self.video_streamer = VideoStreamer(target_ip, video_port)
        self.audio_streamer = AudioStreamer(target_ip, audio_port)

    def start_streaming(self, video_fps=8):
        print("🚀 Starting Audio-Video streaming...")
        audio_thread = threading.Thread(target=self.audio_streamer.start_streaming)
        audio_thread.daemon = True
        audio_thread.start()
        time.sleep(2)
        try:
            self.video_streamer.start_streaming(fps=video_fps)
        except KeyboardInterrupt:
            print("\n🛑 Stopping streamer...")
        finally:
            self.stop_streaming()

    def stop_streaming(self):
        self.video_streamer.stop_streaming()
        self.audio_streamer.stop_streaming()
        print("✅ Streaming stopped")


def main():
    target_ip = sys.argv[1] if len(sys.argv) > 1 else ("192.168.0.237"
                                                       "")
    fps = 8
    if len(sys.argv) > 2:
        try:
            fps = int(sys.argv[2])
        except ValueError:
            pass
    streamer = AVStreamer(target_ip)
    try:
        streamer.start_streaming(video_fps=fps)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        print("✅ Application exited")


if __name__ == "__main__":
    main()
