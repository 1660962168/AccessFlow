import subprocess
import time
import os
import sys
# 新增：导入这个库来自动查找 ffmpeg 路径
import imageio_ffmpeg 

def start_rtsp_stream(video_path, rtsp_url):
    """
    使用 FFmpeg 将本地视频循环推送到 RTSP 地址
    """
    if not os.path.exists(video_path):
        print(f"[错误] 找不到视频文件: {video_path}")
        return None

    # --- 关键修改：获取 ffmpeg 的绝对路径 ---
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    # -------------------------------------

    # FFmpeg 命令
    command = [
        ffmpeg_exe,  # 使用获取到的绝对路径，而不是简单的 "ffmpeg"
        "-re", 
        "-stream_loop", "-1",
        "-i", video_path,
        "-c", "copy",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        rtsp_url
    ]

    print(f"--> 正在启动流: {rtsp_url}")
    print(f"    (源文件: {video_path})")
    
    # 启动子进程
    # 注意：如果推流依然失败，可以把 stderr=subprocess.DEVNULL 改为 stderr=None
    # 这样可以在控制台看到 FFmpeg 具体的报错信息
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return process

def main():
    # --- 配置区域 ---
    server_base = "rtsp://127.0.0.1:8554"
    
    video1 = "./RtspVideo/entrance.mp4"
    stream1_name = "entrance" 
    
    video2 = "./RtspVideo/Export.mp4"
    stream2_name = "export"   
    
    # --- 启动推流 ---
    print("=== 虚拟 RTSP 推流服务启动 ===")
    print("请确保已运行 mediamtx.exe 服务器...")
    print("-" * 30)

    p1 = start_rtsp_stream(video1, f"{server_base}/{stream1_name}")
    p2 = start_rtsp_stream(video2, f"{server_base}/{stream2_name}")

    if p1 and p2:
        print("-" * 30)
        print(f"✅ 流 1 地址: {server_base}/{stream1_name}")
        print(f"✅ 流 2 地址: {server_base}/{stream2_name}")
        print("-" * 30)
        print("服务运行中... 按 Ctrl+C 停止")

        try:
            while True:
                time.sleep(1)
                if p1.poll() is not None:
                    print(f"⚠️ 警告: {stream1_name} 流已断开 (可能是视频格式问题)")
                    break
                if p2.poll() is not None:
                    print(f"⚠️ 警告: {stream2_name} 流已断开 (可能是视频格式问题)")
                    break
        except KeyboardInterrupt:
            print("\n正在停止推流...")
    
    if p1: p1.terminate()
    if p2: p2.terminate()
    print("推流已结束。")

if __name__ == "__main__":
    main()