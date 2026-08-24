import argparse
import wave
from pathlib import Path


def crop_wav(input_path, output_path, start_seconds, end_seconds):
    with wave.open(str(input_path), "rb") as src:
        channels = src.getnchannels()
        sample_width = src.getsampwidth()
        sample_rate = src.getframerate()
        total_frames = src.getnframes()

        start_frame = int(start_seconds * sample_rate)
        end_frame = int(end_seconds * sample_rate)

        start_frame = max(0, min(start_frame, total_frames))
        end_frame = max(start_frame, min(end_frame, total_frames))

        src.setpos(start_frame)
        frames = src.readframes(end_frame - start_frame)

    with wave.open(str(output_path), "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sample_width)
        dst.setframerate(sample_rate)
        dst.writeframes(frames)

    duration = (end_frame - start_frame) / sample_rate

    print(f"Saved: {output_path}")
    print(f"Sample rate: {sample_rate} Hz")
    print(f"Channels: {channels}")
    print(f"Duration: {duration:.3f} sec")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)

    args = parser.parse_args()

    crop_wav(
        args.input,
        args.output,
        args.start,
        args.end,
    )
