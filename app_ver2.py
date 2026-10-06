import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime

try:
    import edge_tts
    import gradio as gr
except ImportError as _err:
    print("\n" + "=" * 60)
    print(f"THIEU THU VIEN: {_err}")
    print("Ban dang chay app bang Python KHONG co du thu vien.")
    print("Cach sua: bam dup vao file cai_dat_ver2.bat (chi can lam 1 lan),")
    print("sau do mo app bang file chay_app_ver2.bat.")
    print("=" * 60 + "\n")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Cấu hình chung
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_LIB_DIR = os.path.join(BASE_DIR, "giong_da_luu")  # nơi lưu các giọng mẫu
os.makedirs(VOICE_LIB_DIR, exist_ok=True)

ENGINE_EDGE = "Giọng có sẵn (Edge TTS)"
ENGINE_CLONE = "Giọng của tôi (nhân bản từ file mẫu)"
TEMP_LABEL = "(Dùng file mẫu vừa tải lên bên dưới)"
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

VOICES = {
    "Hoài My (Nữ)": "vi-VN-HoaiMyNeural",
    "Nam Minh (Nam)": "vi-VN-NamMinhNeural",
}
DEFAULT_VOICE_LABEL = "Hoài My (Nữ)"

PREVIEW_WORDS = 14        # ~14 từ tiếng Việt tương đương khoảng 3 giây
EDGE_CHUNK_CHARS = 1500   # kích thước mỗi đoạn khi dùng Edge TTS
CLONE_CHUNK_CHARS = 500   # kích thước mỗi đoạn khi dùng giọng nhân bản
CONCURRENCY = 4           # số đoạn Edge TTS xử lý cùng lúc (hay lỗi thì hạ xuống 2)
MAX_RETRIES = 3           # số lần tự thử lại cho mỗi đoạn Edge TTS

# Tốc độ khi tải xuống: cách nhau 0.25 (giới hạn 0.5x - 2.0x để giữ chất lượng)
SPEED_CHOICES = [(f"{s:g}x", s) for s in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)]
DEFAULT_SPEEDS = [1.0]

# Giọng nói -> văn bản (faster-whisper)
WHISPER_DEVICE = "cpu"        # máy có card NVIDIA đã cài CUDA có thể đổi thành "cuda"
WHISPER_COMPUTE = "int8"      # dùng "float16" nếu đổi sang "cuda"
STT_MODELS = [
    ("Nhanh - small (tải ~0.5 GB)", "small"),
    ("Cân bằng - medium (tải ~1.5 GB)", "medium"),
    ("Chính xác nhất - large-v3 (tải ~3 GB, chạy chậm)", "large-v3"),
]
STT_LANGUAGES = [
    ("Tiếng Việt", "vi"),
    ("Tiếng Anh", "en"),
    ("Tự động nhận diện", "auto"),
]

# ---------------------------------------------------------------------------
# Chất giọng: hiệu ứng âm thanh (xử lý bằng ffmpeg sau khi tạo giọng)
# ---------------------------------------------------------------------------
_LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"

EFFECTS = {
    "Không xử lý": "",
    # Ấm, dày, đều tiếng: hợp kể chuyện, review phim
    "Ấm & dày (khuyên dùng)": (
        "highpass=f=70,"
        "equalizer=f=200:t=q:w=1:g=3,"
        "equalizer=f=3500:t=q:w=1.2:g=1.5,"
        "acompressor=threshold=0.1:ratio=3:attack=15:release=200:makeup=2,"
        + _LOUDNESS
    ),
    # Giọng phát thanh viên: rõ, sáng, nén mạnh hơn
    "Phát thanh (radio)": (
        "highpass=f=90,lowpass=f=9000,"
        "equalizer=f=150:t=q:w=1:g=3,"
        "equalizer=f=5000:t=q:w=1:g=2,"
        "acompressor=threshold=0.08:ratio=4:attack=10:release=150:makeup=2.5,"
        + _LOUDNESS
    ),
    # Như thu trong phòng thu: ấm + chút vang nhẹ
    "Phòng thu (có chút vang)": (
        "highpass=f=70,"
        "equalizer=f=200:t=q:w=1:g=2.5,"
        "acompressor=threshold=0.1:ratio=3:attack=15:release=200:makeup=2,"
        "aecho=0.8:0.88:35|70:0.2|0.12,"
        + _LOUDNESS
    ),
}
DEFAULT_EFFECT = "Ấm & dày (khuyên dùng)"

# Mẫu chất giọng: tốc độ đọc (%), cao độ (Hz), nghỉ giữa các đoạn (giây), hiệu ứng
STYLE_PRESETS = {
    "Kể chuyện / Review phim": dict(rate=-8, pitch=-4, pause=0.7, effect="Ấm & dày (khuyên dùng)"),
    "Thuyết minh / Tin tức": dict(rate=-3, pitch=0, pause=0.5, effect="Phát thanh (radio)"),
    "Podcast tâm sự": dict(rate=-10, pitch=-2, pause=0.8, effect="Phòng thu (có chút vang)"),
    "Sôi động / Quảng cáo": dict(rate=8, pitch=4, pause=0.3, effect="Ấm & dày (khuyên dùng)"),
    "Giọng gốc (không chỉnh)": dict(rate=0, pitch=0, pause=0.0, effect="Không xử lý"),
}
DEFAULT_PRESET = "Kể chuyện / Review phim"

DEMO_TEXT = (
    "Xin chào các bạn! Đây là bản demo chuyển văn bản thành giọng nói tiếng Việt. "
    "Việt Nam là một đất nước xinh đẹp, nằm ở phía đông bán đảo Đông Dương. "
    "Từ Hà Nội nghìn năm văn hiến, qua cố đô Huế trầm mặc, đến Sài Gòn sôi động, "
    "mỗi vùng đất đều mang một nét đặc sắc riêng. "
    "Một tô phở nóng hổi vào buổi sáng, một ly cà phê sữa đá giữa trưa, "
    "hay một buổi chiều lang thang trên phố cổ, tất cả đều là những khoảnh khắc "
    "khiến người ta yêu mến cuộc sống thường ngày. "
    "Bạn hãy thử thay đổi đoạn văn này, chọn giọng đọc khác, "
    "rồi bấm nút Tạo giọng nói để nghe kết quả nhé!"
)

OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "vi_tts_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Tiện ích chung
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """Làm sạch văn bản để giọng đọc không bị vấp vì ký hiệu lạ."""
    text = re.sub(r"https?://\S+", " ", text)                            # bỏ đường link
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)  # bỏ emoji
    text = re.sub(r"[*_#`~^|<>\[\]{}]+", " ", text)                      # bỏ ký hiệu markdown
    text = text.replace("&", " và ").replace("%", " phần trăm")
    text = re.sub(r"\s+[—–-]\s+", ", ", text)                            # gạch ngang -> nghỉ nhẹ
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.!?;:…])", r"\1", text)
    return text.strip()


def prepare_text(text: str) -> str:
    if not text or not text.strip():
        raise gr.Error("Vui lòng nhập văn bản cần chuyển thành giọng nói.")
    cleaned = normalize_text(text)
    if not cleaned:
        raise gr.Error("Văn bản chỉ chứa ký hiệu, không có chữ nào để đọc.")
    return cleaned


def split_text(text: str, max_chars: int) -> list[str]:
    """Chia theo câu, gom lại thành các đoạn không vượt quá max_chars."""
    sentences = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        sentences.extend(re.split(r"(?<=[.!?…;])\s+", line))

    chunks, current = [], ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # câu quá dài: cắt theo từ
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            piece, sentence = sentence[:cut], sentence[cut:].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece)

        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)
    return chunks


def split_paragraphs(text: str, max_chars: int) -> list[tuple[str, bool]]:
    """Chia theo đoạn (mỗi dòng là một đoạn). Trả về [(nội dung, có phải cuối đoạn)]."""
    units = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pieces = split_text(line, max_chars)
        for index, piece in enumerate(pieces):
            units.append((piece, index == len(pieces) - 1))
    return units


def new_output_path(prefix: str, ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(OUTPUT_DIR, f"{prefix}_{stamp}_{uuid.uuid4().hex[:4]}.{ext}")


def make_style(rate, pitch, pause, effect) -> dict:
    return {
        "rate": int(rate or 0),
        "pitch": int(pitch or 0),
        "pause": float(pause or 0),
        "effect": effect if effect in EFFECTS else "Không xử lý",
    }


# ---------------------------------------------------------------------------
# ffmpeg: đổi tốc độ, ghép đoạn, hiệu ứng âm thanh
# ---------------------------------------------------------------------------
def get_ffmpeg() -> str:
    """Ưu tiên ffmpeg có sẵn trên máy, nếu không có thì dùng bản đi kèm imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        raise gr.Error(
            "Chưa có công cụ xử lý âm thanh (ffmpeg). Hãy bấm đúp file cai_dat_ver2.bat "
            "để cài đặt lại, sau đó mở lại app."
        )


def run_ffmpeg(args: list[str], error_msg: str) -> None:
    result = subprocess.run(
        [get_ffmpeg(), "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        tail = (result.stderr or "")[-300:]
        raise gr.Error(f"{error_msg}: {tail}")


def atempo_filter(speed: float) -> str:
    """atempo chỉ nhận 0.5-2.0 mỗi lần, nên nối nhiều lần nếu vượt ngoài khoảng này."""
    filters = []
    while speed > 2.0:
        filters.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        filters.append("atempo=0.5")
        speed /= 0.5
    filters.append(f"atempo={speed:.4f}")
    return ",".join(filters)


def change_speed(src: str, speed: float) -> str:
    """Tạo bản sao của file âm thanh với tốc độ mới (giữ nguyên cao độ giọng)."""
    base, ext = os.path.splitext(os.path.basename(src))
    dst = os.path.join(OUTPUT_DIR, f"{base}_x{speed:g}{ext}")

    args = ["-i", src, "-vn", "-filter:a", atempo_filter(speed)]
    if ext.lower() == ".mp3":
        args += ["-codec:a", "libmp3lame", "-q:a", "2"]
    args.append(dst)
    run_ffmpeg(args, f"Không đổi được tốc độ {speed:g}x")

    if not os.path.exists(dst):
        raise gr.Error(f"Không tạo được file tốc độ {speed:g}x.")
    return dst


def build_speed_files(original: str, speeds, progress) -> list[str]:
    """Tạo danh sách file tải xuống ứng với từng tốc độ đã chọn."""
    speeds = sorted({float(s) for s in (speeds or [])}) or list(DEFAULT_SPEEDS)
    files = []
    for i, speed in enumerate(speeds, start=1):
        if abs(speed - 1.0) < 1e-9:
            files.append(original)
        else:
            progress(
                (i - 1) / len(speeds),
                desc=f"Đang tạo bản tốc độ {speed:g}x ({i}/{len(speeds)})...",
            )
            files.append(change_speed(original, speed))
    return files


def apply_effect(src: str, effect_label: str) -> str:
    """Áp hiệu ứng chất giọng lên một file âm thanh có sẵn (dùng cho giọng nhân bản)."""
    filters = EFFECTS.get(effect_label, "")
    if not filters:
        return src

    base, ext = os.path.splitext(os.path.basename(src))
    dst = os.path.join(OUTPUT_DIR, f"{base}_fx{ext}")
    args = ["-i", src, "-vn", "-af", filters, "-ar", "44100"]
    if ext.lower() == ".mp3":
        args += ["-codec:a", "libmp3lame", "-q:a", "2"]
    args.append(dst)
    run_ffmpeg(args, "Không áp được hiệu ứng chất giọng")
    return dst


def _concat_line(path: str) -> str:
    safe = path.replace("\\", "/").replace("'", "'\\''")
    return f"file '{safe}'"


def assemble_mp3(audios: list[bytes], gaps: list[float], filters: str, out_path: str) -> None:
    """Ghép các đoạn mp3, chèn khoảng lặng giữa các đoạn và áp hiệu ứng (nếu có)."""
    tmp_dir = tempfile.mkdtemp(dir=OUTPUT_DIR)
    try:
        lines = []
        silence_files: dict[float, str] = {}
        for i, (audio, gap) in enumerate(zip(audios, gaps)):
            part = os.path.join(tmp_dir, f"part_{i:04d}.mp3")
            with open(part, "wb") as f:
                f.write(audio)
            lines.append(_concat_line(part))

            if gap > 0:
                if gap not in silence_files:
                    sil = os.path.join(tmp_dir, f"silence_{len(silence_files)}.mp3")
                    run_ffmpeg(
                        [
                            "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                            "-t", f"{gap:.2f}", "-codec:a", "libmp3lame", "-b:a", "48k", sil,
                        ],
                        "Không tạo được khoảng lặng",
                    )
                    silence_files[gap] = sil
                lines.append(_concat_line(silence_files[gap]))

        list_path = os.path.join(tmp_dir, "list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        args = ["-f", "concat", "-safe", "0", "-i", list_path]
        if filters:
            args += ["-af", filters, "-ar", "44100"]
        args += ["-codec:a", "libmp3lame", "-q:a", "3", out_path]
        run_ffmpeg(args, "Không ghép/xử lý được âm thanh")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Thư viện giọng đã lưu
# ---------------------------------------------------------------------------
def saved_voice_files() -> dict[str, str]:
    """Trả về {tên giọng: đường dẫn file mẫu} của các giọng đã lưu."""
    voices = {}
    for filename in sorted(os.listdir(VOICE_LIB_DIR)):
        name, ext = os.path.splitext(filename)
        if ext.lower() in AUDIO_EXTS:
            voices[name] = os.path.join(VOICE_LIB_DIR, filename)
    return voices


def voice_choices() -> list[str]:
    return [TEMP_LABEL] + list(saved_voice_files().keys())


def clean_voice_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", name or "").strip()
    return name[:50]


def save_voice(name: str, ref_audio: str):
    name = clean_voice_name(name)
    if not name:
        return gr.update(), "⚠️ Hãy đặt tên cho giọng (ví dụ: Giọng của tôi)."
    if not ref_audio:
        return gr.update(), "⚠️ Hãy tải lên hoặc thu âm file giọng mẫu trước khi lưu."

    ext = os.path.splitext(ref_audio)[1].lower()
    if ext not in AUDIO_EXTS:
        ext = ".wav"

    # Xóa bản cũ cùng tên (nếu có) rồi lưu bản mới
    for old_name, old_path in saved_voice_files().items():
        if old_name == name:
            os.remove(old_path)
    shutil.copyfile(ref_audio, os.path.join(VOICE_LIB_DIR, name + ext))

    return (
        gr.update(choices=voice_choices(), value=name),
        f"✅ Đã lưu giọng **{name}**. Lần sau chỉ cần chọn trong danh sách.",
    )


def delete_voice(name: str):
    voices = saved_voice_files()
    if name not in voices:
        return gr.update(), "⚠️ Hãy chọn một giọng đã lưu để xóa."
    os.remove(voices[name])
    return (
        gr.update(choices=voice_choices(), value=TEMP_LABEL),
        f"🗑️ Đã xóa giọng **{name}**.",
    )


def refresh_voice_list():
    return gr.update(choices=voice_choices())


def resolve_reference(saved_voice: str, ref_audio: str) -> str:
    """Chọn file mẫu: ưu tiên giọng đã lưu, nếu không thì dùng file vừa tải lên."""
    if saved_voice and saved_voice != TEMP_LABEL:
        path = saved_voice_files().get(saved_voice)
        if not path:
            raise gr.Error(f"Không tìm thấy giọng đã lưu '{saved_voice}'.")
        return path
    if not ref_audio:
        raise gr.Error(
            "Hãy chọn một giọng đã lưu, hoặc tải lên/thu âm file giọng mẫu "
            "dài khoảng 3-8 giây."
        )
    return ref_audio


# ---------------------------------------------------------------------------
# Engine 1: Edge TTS (giọng có sẵn) - chạy song song nhiều đoạn
# ---------------------------------------------------------------------------
async def edge_synth_chunk(text: str, voice: str, rate: str, pitch: str) -> bytes:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = bytearray()
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            async for item in communicate.stream():
                if item["type"] == "audio":
                    data.extend(item["data"])
            if data:
                return bytes(data)
        except Exception as e:  # noqa: BLE001
            last_error = e
        await asyncio.sleep(1.5 * attempt)
    raise RuntimeError(str(last_error) if last_error else "Không nhận được âm thanh")


async def edge_generate(text: str, voice_label: str, progress, style: dict) -> str:
    voice = VOICES.get(voice_label, VOICES[DEFAULT_VOICE_LABEL])
    rate = f"{style['rate']:+d}%"
    pitch = f"{style['pitch']:+d}Hz"
    filters = EFFECTS.get(style["effect"], "")

    units = split_paragraphs(text, EDGE_CHUNK_CHARS)
    total = len(units)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    done = 0
    progress(0, desc=f"Đang xử lý 0/{total} đoạn...")

    async def worker(part: str) -> bytes:
        nonlocal done
        async with semaphore:
            audio = await edge_synth_chunk(part, voice, rate, pitch)
        done += 1
        progress(done / total, desc=f"Đang xử lý {done}/{total} đoạn...")
        return audio

    results = await asyncio.gather(
        *(worker(chunk) for chunk, _ in units), return_exceptions=True
    )
    for index, result in enumerate(results, start=1):
        if isinstance(result, Exception):
            raise gr.Error(
                f"Đoạn {index}/{total} bị lỗi: {result}. "
                "Hãy thử lại sau ít phút, hoặc hạ CONCURRENCY xuống 2 trong app.py."
            )

    # Khoảng nghỉ chỉ chèn ở cuối mỗi đoạn văn (trừ đoạn cuối cùng)
    gaps = [style["pause"] if is_end else 0.0 for _, is_end in units]
    gaps[-1] = 0.0

    path = new_output_path("giong_noi", "mp3")
    if not filters and not any(gaps):
        with open(path, "wb") as f:  # đường nhanh: chỉ nối các đoạn lại
            for audio in results:
                f.write(audio)
    else:
        progress(1, desc="Đang ghép đoạn và xử lý chất giọng...")
        await asyncio.to_thread(assemble_mp3, results, gaps, filters, path)
    return path


# ---------------------------------------------------------------------------
# Engine 2: VieNeu-TTS (nhân bản giọng từ file mẫu 3-8 giây)
# ---------------------------------------------------------------------------
_clone_model = None
_clone_lock = threading.Lock()


def get_clone_model():
    """Nạp mô hình lần đầu sau khi mở app (có thể lâu), các lần sau dùng lại."""
    global _clone_model
    if _clone_model is None:
        try:
            from vieneu import Vieneu
        except ImportError:
            raise gr.Error(
                "Chưa cài thư viện nhân bản giọng. Hãy chạy lệnh: "
                "python -m pip install vieneu (dùng Python 3.12, xem hướng dẫn)."
            )
        _clone_model = Vieneu()
    return _clone_model


def preload_clone_model():
    """Nạp ngầm mô hình ngay khi mở app để lúc bấm tạo giọng không phải chờ."""
    try:
        with _clone_lock:
            get_clone_model()
    except Exception:  # noqa: BLE001
        pass  # chưa cài vieneu thì bỏ qua, Edge TTS vẫn dùng bình thường


def clone_generate_sync(text: str, ref_path: str, progress) -> str:
    import numpy as np

    if _clone_model is None:
        progress(0, desc="Đang nạp mô hình vào bộ nhớ (chỉ chậm 1 lần mỗi khi mở app)...")
    else:
        progress(0, desc="Đang xử lý...")

    with _clone_lock:
        tts = get_clone_model()
        chunks = split_text(text, CLONE_CHUNK_CHARS)
        total = len(chunks)
        pieces = []
        for i, part in enumerate(chunks, start=1):
            progress((i - 1) / total, desc=f"Đang xử lý {i}/{total} đoạn...")
            try:
                pieces.append(tts.infer(part, ref_audio=ref_path, denoise=True))
            except Exception as e:  # noqa: BLE001
                raise gr.Error(f"Đoạn {i}/{total} bị lỗi: {e}")

        audio = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
        path = new_output_path("giong_cua_toi", "wav")
        tts.save(audio, path)
    progress(1, desc="Hoàn tất")
    return path


# ---------------------------------------------------------------------------
# Giọng nói -> văn bản (faster-whisper)
# ---------------------------------------------------------------------------
_whisper_models = {}
_whisper_lock = threading.Lock()


def get_whisper_model(size: str):
    """Nạp mô hình nhận dạng. Chỉ giữ 1 mô hình trong RAM để tiết kiệm bộ nhớ."""
    with _whisper_lock:
        if size not in _whisper_models:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise gr.Error(
                    "Chưa cài thư viện nhận dạng giọng nói. Hãy bấm đúp file "
                    "cai_dat_ver2.bat (chạy lại 1 lần) rồi mở lại app."
                )
            _whisper_models.clear()
            _whisper_models[size] = WhisperModel(
                size, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE
            )
        return _whisper_models[size]


def format_time(seconds: float, srt: bool = False) -> str:
    ms_total = int(round(seconds * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}" if srt else f"{h:02d}:{m:02d}:{s:02d}"


def transcribe_sync(audio_path: str, model_size: str, language: str, with_ts: bool, progress):
    progress(0, desc="Đang nạp mô hình nhận dạng (lần đầu sẽ tải về, có thể mất vài phút)...")
    model = get_whisper_model(model_size)

    lang = None if language == "auto" else language
    try:
        segments, info = model.transcribe(
            audio_path, language=lang, beam_size=5, vad_filter=True
        )
        duration = info.duration or 0

        text_lines, srt_blocks = [], []
        for seg in segments:  # segments là generator, nhận dạng diễn ra tại vòng lặp này
            text = seg.text.strip()
            if not text:
                continue
            if with_ts:
                text_lines.append(
                    f"[{format_time(seg.start)} → {format_time(seg.end)}] {text}"
                )
            else:
                text_lines.append(text)
            srt_blocks.append(
                f"{len(srt_blocks) + 1}\n"
                f"{format_time(seg.start, srt=True)} --> {format_time(seg.end, srt=True)}\n"
                f"{text}\n"
            )
            if duration:
                progress(
                    min(seg.end / duration, 0.99),
                    desc=f"Đang nhận dạng... {format_time(seg.end)} / {format_time(duration)}",
                )
    except gr.Error:
        raise
    except Exception as e:  # noqa: BLE001
        raise gr.Error(f"Không nhận dạng được file này: {e}")

    if not text_lines:
        raise gr.Error("Không nghe thấy lời nói nào trong file âm thanh.")

    full_text = "\n".join(text_lines)

    txt_path = new_output_path("van_ban", "txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    srt_path = new_output_path("phu_de", "srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_blocks))

    progress(1, desc="Hoàn tất")
    return full_text, [txt_path, srt_path]


# ---------------------------------------------------------------------------
# Các hàm cho giao diện
# ---------------------------------------------------------------------------
async def synthesize(text, engine, voice_label, saved_voice, ref_audio, style, progress):
    """Tạo giọng nói theo engine đã chọn, đã áp chất giọng."""
    if engine == ENGINE_CLONE:
        ref_path = resolve_reference(saved_voice, ref_audio)
        path = await asyncio.to_thread(clone_generate_sync, text, ref_path, progress)
        # Giọng nhân bản chỉ áp được hiệu ứng âm thanh (không có tốc độ/cao độ/nghỉ đoạn)
        return await asyncio.to_thread(apply_effect, path, style["effect"])
    return await edge_generate(text, voice_label, progress, style)


async def preview_voice(
    text, engine, voice_label, saved_voice, ref_audio,
    rate, pitch, pause, effect, progress=gr.Progress(),
):
    """Nghe thử: chỉ đọc vài từ đầu tiên (khoảng 2-3 giây), có áp chất giọng."""
    text = prepare_text(text)
    short_text = " ".join(text.split()[:PREVIEW_WORDS])
    style = make_style(rate, pitch, pause, effect)

    path = await synthesize(short_text, engine, voice_label, saved_voice, ref_audio, style, progress)
    return path, None  # bản nghe thử không cho tải


async def generate_voice(
    text, engine, voice_label, saved_voice, ref_audio,
    rate, pitch, pause, effect, speeds, progress=gr.Progress(),
):
    """Tạo giọng nói cho toàn bộ văn bản, rồi tạo thêm các bản tốc độ đã chọn."""
    text = prepare_text(text)
    style = make_style(rate, pitch, pause, effect)

    path = await synthesize(text, engine, voice_label, saved_voice, ref_audio, style, progress)

    files = await asyncio.to_thread(build_speed_files, path, speeds, progress)
    progress(1, desc="Hoàn tất")
    return path, files  # khung nghe luôn ở tốc độ gốc, danh sách tải gồm mọi tốc độ


async def transcribe_audio(
    audio, model_size, language, with_ts, progress=gr.Progress()
):
    """Chuyển giọng nói trong file âm thanh thành văn bản."""
    if not audio:
        raise gr.Error("Hãy tải lên hoặc thu âm file âm thanh cần chuyển thành văn bản.")
    return await asyncio.to_thread(
        transcribe_sync, audio, model_size, language, with_ts, progress
    )


def toggle_engine(engine):
    is_clone = engine == ENGINE_CLONE
    return gr.update(visible=not is_clone), gr.update(visible=is_clone)


def apply_preset(name):
    preset = STYLE_PRESETS.get(name)
    if not preset:
        return gr.update(), gr.update(), gr.update(), gr.update()
    return preset["rate"], preset["pitch"], preset["pause"], preset["effect"]


# ---------------------------------------------------------------------------
# Giao diện
# ---------------------------------------------------------------------------
_default_style = STYLE_PRESETS[DEFAULT_PRESET]

with gr.Blocks(title="Văn bản và giọng nói tiếng Việt (ver2)") as demo:
    gr.Markdown("# 🎙️ Văn bản ⇄ Giọng nói tiếng Việt")

    with gr.Tabs():
        # ------------------------- Phần 1: Văn bản -> Giọng nói -------------------------
        with gr.Tab("📝 Văn bản → Giọng nói"):
            gr.Markdown(
                "Chọn giọng có sẵn, hoặc dùng **giọng của bạn** (lưu một lần, dùng lại mãi)."
            )

            text_input = gr.Textbox(
                label="Văn bản",
                value=DEMO_TEXT,
                lines=10,
                placeholder="Nhập văn bản tiếng Việt tại đây...",
                info="Mẹo cho giọng có hồn: viết câu ngắn, dùng dấu phẩy để ngắt hơi, "
                "xuống dòng để chuyển ý (giọng sẽ nghỉ lâu hơn ở chỗ xuống dòng).",
            )

            engine_radio = gr.Radio(
                label="Kiểu giọng",
                choices=[ENGINE_EDGE, ENGINE_CLONE],
                value=ENGINE_EDGE,
            )

            with gr.Group(visible=True) as edge_group:
                voice_dropdown = gr.Dropdown(
                    label="Giọng đọc",
                    choices=list(VOICES.keys()),
                    value=DEFAULT_VOICE_LABEL,
                )

            with gr.Group(visible=False) as clone_group:
                saved_dropdown = gr.Dropdown(
                    label="Giọng đã lưu",
                    choices=voice_choices(),
                    value=TEMP_LABEL,
                )
                with gr.Accordion("➕ Thêm giọng mới / 🗑️ Xóa giọng", open=False):
                    ref_audio_input = gr.Audio(
                        label="Giọng mẫu (3-8 giây, rõ tiếng, một người nói, không nhạc nền)",
                        sources=["upload", "microphone"],
                        type="filepath",
                    )
                    voice_name_input = gr.Textbox(
                        label="Đặt tên cho giọng này", placeholder="Ví dụ: Giọng của tôi"
                    )
                    with gr.Row():
                        save_btn = gr.Button("💾 Lưu giọng này")
                        delete_btn = gr.Button("🗑️ Xóa giọng đang chọn ở trên")
                    lib_status = gr.Markdown()
                gr.Markdown(
                    "⚠️ Chỉ dùng giọng của **chính bạn** hoặc giọng của người "
                    "**đã đồng ý** cho bạn sử dụng. Mô hình được nạp ngầm mỗi khi mở app "
                    "nên lần đầu có thể mất vài phút. Mẹo: giọng mẫu đọc có ngữ điệu "
                    "(kể chuyện, truyền cảm) thường cho giọng ra sinh động hơn mẫu đọc đều đều."
                )

            # ----- Chất giọng -----
            preset_dropdown = gr.Dropdown(
                label="🎭 Chất giọng",
                choices=list(STYLE_PRESETS.keys()),
                value=DEFAULT_PRESET,
                info="Chọn nhanh một phong cách, hoặc tự tinh chỉnh ở mục bên dưới.",
            )
            with gr.Accordion("🎛️ Tinh chỉnh chất giọng", open=False):
                gr.Markdown(
                    "Tốc độ đọc, cao độ và độ nghỉ giữa các đoạn chỉ áp dụng cho "
                    "**giọng có sẵn (Edge TTS)**. Hiệu ứng âm thanh áp dụng cho cả hai kiểu giọng."
                )
                rate_slider = gr.Slider(
                    minimum=-40, maximum=40, step=1, value=_default_style["rate"],
                    label="Tốc độ đọc (%)",
                    info="Âm = chậm, rãi hơn (hợp kể chuyện). Dương = nhanh hơn.",
                )
                pitch_slider = gr.Slider(
                    minimum=-30, maximum=30, step=1, value=_default_style["pitch"],
                    label="Cao độ (Hz)",
                    info="Âm = trầm, ấm hơn. Dương = cao, sáng hơn.",
                )
                pause_slider = gr.Slider(
                    minimum=0, maximum=2, step=0.1, value=_default_style["pause"],
                    label="Nghỉ giữa các đoạn (giây)",
                    info="Khoảng lặng chèn vào mỗi chỗ xuống dòng trong văn bản.",
                )
                effect_dropdown = gr.Dropdown(
                    label="Hiệu ứng âm thanh",
                    choices=list(EFFECTS.keys()),
                    value=_default_style["effect"],
                    info="Làm giọng ấm, dày và đều tiếng hơn, bớt cảm giác khô cứng như máy.",
                )

            speed_group = gr.CheckboxGroup(
                label="Tốc độ khi tải xuống (có thể chọn nhiều tốc độ)",
                choices=SPEED_CHOICES,
                value=DEFAULT_SPEEDS,
                info="Khung nghe bên dưới luôn phát ở tốc độ gốc (1x). "
                "Mỗi tốc độ được chọn sẽ tạo ra một file riêng để tải về.",
            )

            with gr.Row():
                preview_btn = gr.Button("🔊 Nghe thử (khoảng 3 giây)")
                generate_btn = gr.Button("Tạo giọng nói", variant="primary")

            audio_output = gr.Audio(label="Kết quả (tốc độ gốc)", type="filepath")
            file_output = gr.File(
                label="⬇️ Tải file giọng nói (mỗi tốc độ một file)",
                file_count="multiple",
            )

        # ------------------------- Phần 2: Giọng nói -> Văn bản -------------------------
        with gr.Tab("🎧 Giọng nói → Văn bản"):
            gr.Markdown(
                "Tải lên hoặc thu âm giọng nói, app sẽ chép lại thành văn bản. "
                "Lần đầu dùng mỗi mô hình sẽ phải tải về nên có thể mất vài phút."
            )

            stt_audio = gr.Audio(
                label="File âm thanh cần chuyển thành văn bản",
                sources=["upload", "microphone"],
                type="filepath",
            )
            with gr.Row():
                stt_model = gr.Dropdown(
                    label="Mô hình nhận dạng",
                    choices=STT_MODELS,
                    value="small",
                )
                stt_language = gr.Dropdown(
                    label="Ngôn ngữ trong file",
                    choices=STT_LANGUAGES,
                    value="vi",
                )
            stt_timestamps = gr.Checkbox(
                label="Hiển thị mốc thời gian trước mỗi câu", value=False
            )
            stt_btn = gr.Button("📝 Chuyển thành văn bản", variant="primary")

            stt_text = gr.Textbox(
                label="Văn bản kết quả", lines=14, interactive=True
            )
            stt_files = gr.File(
                label="⬇️ Tải kết quả (.txt là văn bản, .srt là phụ đề có mốc thời gian)",
                file_count="multiple",
            )

    # ------------------------- Kết nối sự kiện -------------------------
    engine_radio.change(
        fn=toggle_engine, inputs=engine_radio, outputs=[edge_group, clone_group]
    )
    preset_dropdown.change(
        fn=apply_preset,
        inputs=preset_dropdown,
        outputs=[rate_slider, pitch_slider, pause_slider, effect_dropdown],
    )
    save_btn.click(
        fn=save_voice,
        inputs=[voice_name_input, ref_audio_input],
        outputs=[saved_dropdown, lib_status],
    )
    delete_btn.click(
        fn=delete_voice, inputs=saved_dropdown, outputs=[saved_dropdown, lib_status]
    )
    demo.load(fn=refresh_voice_list, outputs=saved_dropdown)

    preview_inputs = [
        text_input, engine_radio, voice_dropdown, saved_dropdown, ref_audio_input,
        rate_slider, pitch_slider, pause_slider, effect_dropdown,
    ]
    generate_inputs = preview_inputs + [speed_group]
    tts_outputs = [audio_output, file_output]
    preview_btn.click(fn=preview_voice, inputs=preview_inputs, outputs=tts_outputs)
    generate_btn.click(fn=generate_voice, inputs=generate_inputs, outputs=tts_outputs)

    stt_btn.click(
        fn=transcribe_audio,
        inputs=[stt_audio, stt_model, stt_language, stt_timestamps],
        outputs=[stt_text, stt_files],
    )

if __name__ == "__main__":
    threading.Thread(target=preload_clone_model, daemon=True).start()
    demo.launch(inbrowser=True, share=True)
