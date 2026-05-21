import subprocess
import imageio_ffmpeg
import sys

def convert_to_wav(input_path, output_path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([
        ffmpeg, '-y', '-i', input_path,
        '-ar', '24000', '-ac', '1',
        output_path
    ], check=True)
    print(f"轉換完成：{output_path}")

if __name__ == "__main__":
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    convert_to_wav(input_path, output_path)