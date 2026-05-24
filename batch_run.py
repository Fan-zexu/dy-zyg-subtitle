#!/Users/zhangnan53/Desktop/xcodezip/Xcode.app/Contents/Developer/usr/bin/python3
"""
抖音博主视频字幕批量提取 - 增强版 v2
====================================
特性：
1. 每个视频独立文件夹（序号_标题）
2. 多进程并行（充分利用 CPU）
3. 进度持久化（JSON 文件记录，断点续传）
4. 使用 Whisper medium 模型（直接 Python API 调用）
5. 每个视频处理完立即写入进度文件

使用方法：
    python3 batch_run.py
"""

import json
import os
import re
import sys
import time
import logging
import subprocess
import multiprocessing
from pathlib import Path
from datetime import datetime

import requests
import browser_cookie3

# ============================================================
# 配置
# ============================================================

OUTPUT_DIR = Path("/Users/zhangnan53/workspace/dy/治愈果")
VIDEO_LIST_FILE = OUTPUT_DIR / "_video_list.json"
PROGRESS_FILE = OUTPUT_DIR / "_batch_progress.json"
WHISPER_MODEL = "medium"
MAX_WORKERS = 2  # 并发进程数（medium模型吃内存，2并发更稳定）
SKIP_SHORT = 10  # 跳过小于10秒的视频
FFMPEG = "/opt/homebrew/bin/ffmpeg"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s %(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("batch")

# ============================================================
# 工具函数
# ============================================================

def safe_filename(title: str) -> str:
    """生成安全的文件名"""
    safe = re.sub(r'[\\/*?:"<>|\n\r\t#@]', "_", title)
    safe = re.sub(r'_+', '_', safe).strip("_. ")
    return safe[:60] if safe else "untitled"


def load_progress() -> dict:
    """加载进度"""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"completed": {}, "failed": {}, "skipped": {}, "start_time": time.time()}


def save_progress(progress: dict):
    """保存进度（原子写入）"""
    progress["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp_file = PROGRESS_FILE.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    tmp_file.rename(PROGRESS_FILE)


def load_video_list() -> list:
    """加载视频列表"""
    if not VIDEO_LIST_FILE.exists():
        logger.error(f"视频列表文件不存在: {VIDEO_LIST_FILE}")
        sys.exit(1)
    return json.loads(VIDEO_LIST_FILE.read_text(encoding="utf-8"))


# ============================================================
# 单视频处理函数（在子进程中运行）
# ============================================================

def process_single_video(args: tuple) -> dict:
    """
    处理单个视频（子进程入口）
    返回: {video_id, success, error, source, output_file, title, idx, folder_name}
    """
    idx, video_id, title, duration, play_urls, video_dir_str, folder_name = args

    video_dir = Path(video_dir_str)
    result = {
        "video_id": video_id,
        "idx": idx,
        "title": title,
        "folder_name": folder_name,
        "success": False,
        "error": "",
        "source": "",
        "output_file": "",
    }

    video_dir.mkdir(parents=True, exist_ok=True)

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }

    MOBILE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://www.douyin.com/",
    }

    # 获取播放地址
    video_url = ""
    if play_urls:
        video_url = play_urls[0].replace("playwm", "play")
    else:
        share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
        try:
            resp = requests.get(share_url, headers=MOBILE_HEADERS, timeout=15)
            resp.raise_for_status()
            pattern = r'"play_addr":\s*\{[^}]*"url_list":\s*\["([^"]+)"'
            m = re.search(pattern, resp.text)
            if m:
                video_url = m.group(1).replace("playwm", "play")
        except:
            pass

    if not video_url:
        result["error"] = "无法获取播放地址"
        return result

    # 下载视频
    video_tmp = video_dir / f"_tmp_video.mp4"
    audio_tmp = video_dir / f"_tmp_audio.mp3"

    try:
        resp = requests.get(video_url, headers=DEFAULT_HEADERS, stream=True, timeout=120)
        resp.raise_for_status()
        with open(video_tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        result["error"] = f"视频下载失败: {e}"
        _cleanup(video_tmp, audio_tmp)
        return result

    # 提取音频
    try:
        proc = subprocess.run(
            [FFMPEG, "-i", str(video_tmp), "-vn", "-acodec", "libmp3lame",
             "-q:a", "4", str(audio_tmp), "-y"],
            capture_output=True, timeout=120
        )
        if proc.returncode != 0:
            result["error"] = "ffmpeg 音频提取失败"
            _cleanup(video_tmp, audio_tmp)
            return result
    except Exception as e:
        result["error"] = f"ffmpeg 异常: {e}"
        _cleanup(video_tmp, audio_tmp)
        return result

    # 删除视频临时文件
    _cleanup(video_tmp)

    # Whisper 转录（直接用 Python API）
    try:
        import whisper
        model = whisper.load_model(WHISPER_MODEL)
        transcribe_result = model.transcribe(
            str(audio_tmp),
            language="zh",
            verbose=False
        )
        segments = transcribe_result.get("segments", [])

        if not segments:
            result["error"] = "Whisper 转录结果为空"
            _cleanup(audio_tmp)
            return result

        # 生成输出文件
        safe_title = safe_filename(title)
        final_srt = video_dir / f"{safe_title}.srt"
        final_txt = video_dir / f"{safe_title}.txt"
        final_md = video_dir / f"{safe_title}.md"

        # 写 SRT
        srt_content = generate_srt(segments)
        final_srt.write_text(srt_content, encoding="utf-8")

        # 写 TXT
        txt_content = " ".join(seg["text"].strip() for seg in segments)
        final_txt.write_text(txt_content, encoding="utf-8")

        # 写 MD
        md_segments = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in segments]
        md_content = generate_markdown(title, video_id, f"whisper_{WHISPER_MODEL}", md_segments)
        final_md.write_text(md_content, encoding="utf-8")

        result["success"] = True
        result["source"] = f"whisper_{WHISPER_MODEL}"
        result["output_file"] = str(final_md)

        # 清理音频临时文件
        _cleanup(audio_tmp)

    except Exception as e:
        result["error"] = f"Whisper 异常: {str(e)[:200]}"
        _cleanup(audio_tmp)

    return result


def _cleanup(*paths):
    """清理临时文件"""
    for p in paths:
        try:
            if p and Path(p).exists():
                os.remove(p)
        except OSError:
            pass


def generate_srt(segments: list) -> str:
    """生成 SRT 格式"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start_ts = _format_srt_time(seg["start"])
        end_ts = _format_srt_time(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}")
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _seconds_to_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"[{h:02d}:{m:02d}:{s:02d}]"
    return f"[{m:02d}:{s:02d}]"


def generate_markdown(title: str, video_id: str, source: str, segments: list) -> str:
    """生成 Markdown 格式文字稿"""
    lines = [
        f"# {title}",
        "",
        f"- 视频ID: {video_id}",
        f"- 链接: https://www.douyin.com/video/{video_id}",
        f"- 字幕来源: {source}",
        f"- 字幕段数: {len(segments)}",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 带时间戳文字稿",
        "",
    ]
    for seg in segments:
        ts = _seconds_to_timestamp(seg["start"])
        lines.append(f"{ts} {seg['text']}")

    lines.extend(["", "## 纯文字稿", ""])
    full_text = "".join(seg["text"] for seg in segments)
    for i in range(0, len(full_text), 200):
        lines.append(full_text[i:i + 200])
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("抖音视频字幕批量提取 - 增强版 v2")
    logger.info(f"Whisper 模型: {WHISPER_MODEL} | 并发数: {MAX_WORKERS}")
    logger.info("=" * 60)

    # 加载视频列表
    videos = load_video_list()
    logger.info(f"视频总数: {len(videos)}")

    # 加载进度
    progress = load_progress()
    completed_ids = set(progress["completed"].keys())
    failed_ids = set(progress["failed"].keys())
    skipped_ids = set(progress["skipped"].keys())

    logger.info(f"已完成: {len(completed_ids)} | 已失败: {len(failed_ids)} | 已跳过: {len(skipped_ids)}")

    # 筛选待处理视频
    tasks = []
    for i, video in enumerate(videos, 1):
        video_id = video["aweme_id"]
        title = video.get("desc", "") or f"douyin_{video_id}"
        duration = video.get("duration", 0)

        # 跳过已完成
        if video_id in completed_ids:
            continue

        # 跳过太短的
        if duration < SKIP_SHORT:
            if video_id not in skipped_ids:
                progress["skipped"][video_id] = {
                    "reason": f"时长过短({duration}秒)",
                    "title": title[:80],
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_progress(progress)
            continue

        # 构建文件夹名
        folder_name = f"{i:03d}_{safe_filename(title)}"
        video_dir = OUTPUT_DIR / folder_name

        tasks.append((
            i, video_id, title, duration,
            video.get("play_urls", []),
            str(video_dir), folder_name
        ))

    logger.info(f"待处理: {len(tasks)} 个视频")
    logger.info("-" * 60)

    if not tasks:
        logger.info("所有视频已处理完毕！")
        return 0

    # 多进程并行处理
    success_count = 0
    fail_count = 0
    total_tasks = len(tasks)

    # 使用 Pool 进行并行处理
    pool = multiprocessing.Pool(processes=MAX_WORKERS)

    try:
        results_iter = pool.imap_unordered(process_single_video, tasks)

        for result in results_iter:
            video_id = result["video_id"]

            if result["success"]:
                success_count += 1
                progress["completed"][video_id] = {
                    "title": result["title"][:100],
                    "folder": result["folder_name"],
                    "file": result["output_file"],
                    "source": result["source"],
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                done_total = len(progress["completed"])
                logger.info(
                    f"[OK {done_total}/{total_tasks + len(completed_ids)}] "
                    f"#{result['idx']} {result['title'][:50]}"
                )
            else:
                fail_count += 1
                progress["failed"][video_id] = {
                    "title": result["title"][:100],
                    "error": result["error"],
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                logger.warning(
                    f"[FAIL] #{result['idx']} {result['title'][:40]} | {result['error'][:80]}"
                )

            # 每次处理完一个视频立即保存进度
            save_progress(progress)
            sys.stdout.flush()

    except KeyboardInterrupt:
        logger.info("\n收到中断信号，正在保存进度...")
        pool.terminate()
        save_progress(progress)
    finally:
        pool.close()
        pool.join()

    # 最终统计
    logger.info("")
    logger.info("=" * 60)
    logger.info("批量处理完成!")
    logger.info(f"  本次成功: {success_count}")
    logger.info(f"  本次失败: {fail_count}")
    logger.info(f"  累计完成: {len(progress['completed'])}")
    logger.info(f"  累计跳过: {len(progress['skipped'])}")
    logger.info(f"  输出目录: {OUTPUT_DIR}")

    return 0


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    sys.exit(main())
