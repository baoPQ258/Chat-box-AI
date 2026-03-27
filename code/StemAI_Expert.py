import streamlit as st
from groq import Groq
import pdfplumber
import PyPDF2
import os
import re
import math
from collections import Counter
from dotenv import load_dotenv

import streamlit.components.v1 as components
import hashlib
import io
from gtts import gTTS
import base64
load_dotenv()
api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)
# ============================================================
# 1. CẤU HÌNH
# ============================================================
# Lấy đường dẫn của thư mục chứa file script hiện tại
current_dir = os.path.dirname(os.path.abspath(__file__))
# Kết nối với thư mục data nằm cùng cấp với file script
DATA_DIR = os.path.join(current_dir, "data")
MAX_CONTEXT_CHARS = 12000
CHUNK_SIZE = 800    # Tăng lên để giữ tiêu đề + nội dung cùng 1 chunk
CHUNK_OVERLAP = 150
TOP_K_CHUNKS = 8

# ============================================================
# 2. KHỞI TẠO CLIENT
# ============================================================

client = Groq(api_key=api_key)



# ============================================================
# 3. GOOGLE TTS TIẾNG VIỆT
# ============================================================
def clean_text_for_tts(text: str) -> str:
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'[-•]\s+', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[\U0001F300-\U0001FFFF]', '', text)
    text = re.sub(r'[✅⚠️💡🔍📚👨\u200d🏫🎓📕▌]', '', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()[:2000]

@st.cache_data(show_spinner=False, max_entries=50)
def generate_tts_audio(text: str) -> str:
    try:
        tts = gTTS(text=text, lang="vi", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception:
        return ""

def tts_widget(text: str, msg_id: str, rate: float = 0.95) -> None:
    clean = clean_text_for_tts(text)
    if not clean:
        return

    audio_b64 = generate_tts_audio(clean)
    if not audio_b64:
        return

    html = f"""
<div style="margin-top:6px;display:flex;align-items:center;gap:10px;">
  <button id="tts-btn-{msg_id}" onclick="toggleAudio_{msg_id}()"
    style="display:inline-flex;align-items:center;gap:6px;padding:5px 14px;
           border-radius:20px;border:1px solid #d0d7de;background:#f6f8fa;
           color:#444;font-size:13px;cursor:pointer;transition:all 0.2s;"
    onmouseover="this.style.background='#e8f0fe';this.style.borderColor='#1a73e8'"
    onmouseout="this.style.background='#f6f8fa';this.style.borderColor='#d0d7de'">
    🔊 Nghe thầy đọc
  </button>
  <input type="range" id="tts-speed-{msg_id}" min="0.5" max="1.5" step="0.1"
    value="{rate}"
    oninput="setSpeed_{msg_id}(this.value)"
    style="width:80px;accent-color:#1a73e8;"
    title="Tốc độ đọc">
  <span id="tts-speed-label-{msg_id}" style="font-size:12px;color:#888;">{rate}x</span>
  <audio id="tts-audio-{msg_id}"
    src="data:audio/mp3;base64,{audio_b64}"
    preload="auto">
  </audio>
</div>
<script>
(function() {{
  const audio = document.getElementById('tts-audio-{msg_id}');
  const btn   = document.getElementById('tts-btn-{msg_id}');
  const lbl   = document.getElementById('tts-speed-label-{msg_id}');

  window.setSpeed_{msg_id} = function(v) {{
    audio.playbackRate = parseFloat(v);
    lbl.textContent = parseFloat(v).toFixed(1) + 'x';
  }};

  window.toggleAudio_{msg_id} = function() {{
    if (audio.paused) {{
      document.querySelectorAll('audio').forEach(a => {{
        if (a !== audio) {{ a.pause(); a.currentTime = 0; }}
      }});
      audio.play();
    }} else {{
      audio.pause();
      audio.currentTime = 0;
    }}
  }};

  audio.onplay  = () => {{ btn.innerHTML = '⏹ Dừng đọc';      btn.style.background='#e8f0fe'; }};
  audio.onpause = () => {{ btn.innerHTML = '🔊 Nghe thầy đọc'; btn.style.background='#f6f8fa'; }};
  audio.onended = () => {{ btn.innerHTML = '🔊 Nghe thầy đọc'; btn.style.background='#f6f8fa'; }};
  audio.playbackRate = {rate};
}})();
</script>
"""
    components.html(html, height=54)

# ============================================================
# 3. ĐỌC PDF CHÍNH XÁC
# ============================================================
def clean_text(text: str) -> str:
    # FIX: Chuẩn hóa Windows line endings (\r\n) TRƯỚC khi xử lý
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Ghép dòng bị ngắt giữa câu (không kết thúc dấu câu)
    text = re.sub(r'(?<![.!?:\-])\n(?=[a-záàảãạăắặẳẵằâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ])', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def extract_pdf_text(path: str) -> str:
    fname    = os.path.basename(path)
    base     = os.path.splitext(path)[0]
    txt_path = base + ".txt"

    if os.path.exists(txt_path):
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read()
            if text.strip():
                return clean_text(text)
        except Exception:
            pass

    text = ""

    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=2, y_tolerance=3)
                if t:
                    lines = [l for l in t.split("\n")
                             if l.strip() and "blogtailieu.com" not in l.lower()]
                    if lines:
                        text += "\n".join(lines) + "\n"
        if len(text.strip()) > 500:
            return clean_text(text)
    except Exception:
        pass

    text = ""

    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    lines = [l for l in t.split("\n")
                             if l.strip() and "blogtailieu.com" not in l.lower()]
                    if lines:
                        text += "\n".join(lines) + "\n"
        if len(text.strip()) > 500:
            return clean_text(text)
    except Exception as e:
        st.warning(f"⚠️ Không đọc được '{fname}': {e}")

    if not text.strip():
        st.warning(
            f"⚠️ `{fname}`: PDF dạng ảnh scan, đọc được 0 ký tự. "
            f"Hãy đặt file `{os.path.splitext(fname)[0]}.txt` vào thư mục `data/`."
        )
    return ""

# ============================================================
# 3b. CHUNKING
# ============================================================
def build_chunks(text: str) -> list:
    """
    Chunking theo đoạn văn (paragraph-based) thay vì theo câu.
    Ưu điểm:
    - Giữ nguyên tiêu đề bài/chủ đề cùng nội dung của nó
    - Không cắt đứt giữa câu
    - Overlap lấy đoạn văn hoàn chỉnh (không phải nửa câu)
    """
    # Đảm bảo line endings đã sạch
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Tách theo đoạn văn (2+ dòng trống)
    paragraphs = re.split(r'\n{2,}', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p.strip()) > 10]

    chunks = []
    current_parts = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) + 1 <= CHUNK_SIZE:
            # Đoạn này còn vừa → gộp vào chunk hiện tại
            current_parts.append(para)
            current_len += len(para) + 1
        else:
            # Lưu chunk hiện tại
            if current_parts:
                chunks.append('\n'.join(current_parts))

            if len(para) > CHUNK_SIZE:
                # Đoạn quá dài → tách tiếp theo câu
                sentences = re.split(r'(?<=[.!?।])\s+', para)
                sub_parts = []
                sub_len = 0
                for sent in sentences:
                    if sub_len + len(sent) + 1 <= CHUNK_SIZE:
                        sub_parts.append(sent)
                        sub_len += len(sent) + 1
                    else:
                        if sub_parts:
                            chunks.append(' '.join(sub_parts))
                        sub_parts = [sent]
                        sub_len = len(sent)
                # Phần còn lại làm đầu chunk mới
                current_parts = sub_parts
                current_len = sub_len
            else:
                # Bắt đầu chunk mới, thêm overlap từ chunk trước
                if chunks:
                    prev_lines = chunks[-1].split('\n')
                    # Lấy 1-2 dòng cuối của chunk trước làm context
                    overlap_lines = [l for l in prev_lines[-2:] if len(l.strip()) > 15]
                    current_parts = overlap_lines + [para]
                else:
                    current_parts = [para]
                current_len = sum(len(p) for p in current_parts)

    if current_parts:
        chunks.append('\n'.join(current_parts))

    return chunks

@st.cache_resource(show_spinner="📖 Đang nạp và lập chỉ mục tài liệu...")
def load_all_books() -> dict:
    books = {}
    os.makedirs(DATA_DIR, exist_ok=True)

    all_files = [f for f in sorted(os.listdir(DATA_DIR))
                 if f.lower().endswith(".pdf") or f.lower().endswith(".txt")]

    if not all_files:
        st.sidebar.warning(f"⚠️ Thư mục `{DATA_DIR}/` chưa có file PDF hoặc TXT nào!")
        return books

    for fname in all_files:
        fpath = os.path.join(DATA_DIR, fname)

        if fname.lower().endswith(".txt"):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    text = f.read()
                # FIX: chuẩn hóa Windows line endings ngay khi đọc
                text = text.replace('\r\n', '\n').replace('\r', '\n')
            except UnicodeDecodeError:
                try:
                    with open(fpath, "r", encoding="utf-16") as f:
                        text = f.read()
                except Exception as e:
                    st.sidebar.error(f"❌ `{fname}`: lỗi encoding — {e}")
                    continue
            except Exception as e:
                st.sidebar.error(f"❌ `{fname}`: {e}")
                continue
        else:
            text = extract_pdf_text(fpath)

        if not text.strip():
            st.sidebar.error(f"❌ `{fname}`: đọc được 0 ký tự.")
            continue

        text   = clean_text(text)
        chunks = build_chunks(text)
        books[fname] = {"text": text, "chunks": chunks}
        icon = "📄" if fname.lower().endswith(".txt") else "📕"
        st.sidebar.success(f"✅ {icon} `{fname}`: {len(text):,} ký tự · {len(chunks)} đoạn")

    return books

# ============================================================
# 5. TÌM KIẾM BM25 + HYBRID RE-RANKING
# ============================================================
STOP_WORDS = {
    "là","và","của","có","trong","để","với","bạn","tôi","được","các","này","đó",
    "một","cho","em","thầy","cô","hỏi","về","như","thế","nào","gì","khi","hay",
    "rằng","thì","mà","nhưng","còn","vì","nên","đã","sẽ","đang","bị",
    "tại","theo","từ","ra","vào","lên","xuống","đến","qua","lại","cũng","chỉ",
    "hơn","nhất","rất","quá","khá","đều","cả","mọi","ai","đâu","sao","ở",
    "mình","họ","nó","ta","chúng","những","loại","dạng","kiểu","cái","con"
    # LƯU Ý: đã bỏ "số" ra khỏi stop words vì cần để tìm "bài số X"
}

def tokenize(text: str) -> list:
    tokens = []
    for w in re.findall(r'\w+', text.lower()):
        if re.match(r'^\d+$', w):
            # Luôn giữ số (kể cả 1 chữ số như 6, 7, 8, 9)
            # để tìm được "Bài 7", "Lớp 6", "Chủ đề 3"...
            tokens.append(w)
        elif len(w) > 1 and w not in STOP_WORDS:
            tokens.append(w)
    return tokens


class BM25Index:
    def __init__(self, chunks: list, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b  = b
        self.chunks    = chunks
        self.tokenized = [tokenize(c) for c in chunks]
        self.N         = len(chunks)
        self.avgdl     = sum(len(t) for t in self.tokenized) / max(self.N, 1)
        self.df: dict  = Counter()
        for tokens in self.tokenized:
            self.df.update(set(tokens))
        self.tf = [Counter(t) for t in self.tokenized]

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)

    def score(self, query_tokens: list, idx: int) -> float:
        dl, tf, s = len(self.tokenized[idx]), self.tf[idx], 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            freq = tf[term]
            idf  = self._idf(term)
            num  = freq * (self.k1 + 1)
            den  = freq + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1))
            s   += idf * num / den
        return s

    def search(self, query: str, top_k: int = 20) -> list:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scored = [(self.score(q_tokens, i), i) for i in range(self.N)]
        scored.sort(reverse=True)
        return [(s, i) for s, i in scored if s > 0][:top_k]


def exact_match_bonus(query: str, chunk: str) -> float:
    q, c  = query.lower(), chunk.lower()
    bonus = 0.0
    # Từ >= 4 ký tự
    for word in re.findall(r'\w{4,}', q):
        if word in c:
            bonus += 0.3
    # Số (kể cả 1-2 chữ số như "7", "10") — quan trọng cho "Bài 7", "Lớp 6"
    for num in re.findall(r'\b\d+\b', q):
        if re.search(rf'\b{num}\b', c):
            bonus += 1.0
    # Cụm 2-3 từ liên tiếp
    words = q.split()
    for n in (3, 2):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i+n])
            if phrase in c:
                bonus += 1.5 * n
    return bonus


@st.cache_resource(show_spinner="🔍 Đang xây dựng chỉ mục BM25...")
def build_search_index(books_key: str, books: dict) -> tuple:
    all_chunks = []
    for fname, data in books.items():
        for chunk in data["chunks"]:
            if len(chunk.strip()) > 50:
                all_chunks.append((chunk, fname))

    if not all_chunks:
        return [], None

    texts = [c[0] for c in all_chunks]
    index = BM25Index(texts)
    return all_chunks, index


def expand_query(query: str) -> str:
    """
    Mở rộng query để tìm kiếm chính xác hơn.
    VD: 'bài 7 tên là gì' → thêm 'BÀI 7 tên chủ đề 7'
    Giúp BM25 match được cả dạng viết hoa trong sách.
    """
    q = query.strip()
    expanded = q

    # Phát hiện hỏi về bài/chủ đề cụ thể
    m = re.search(r'(?:bài|chủ\s*đề|chương)\s*(\d+)', q, re.IGNORECASE)
    if m:
        num = m.group(1)
        # Thêm dạng viết hoa (như trong sách)
        expanded += f" BÀI {num} CHỦ ĐỀ {num} bài {num}"

    return expanded


def find_relevant_context(query: str, books: dict) -> tuple:
    if not books:
        return "", []

    books_key = "|".join(sorted(books.keys()))
    all_chunks, index = build_search_index(books_key, books)

    if not all_chunks or index is None:
        return "", []

    # Mở rộng query (thêm dạng viết hoa, số bài...)
    expanded = expand_query(query)

    candidates = index.search(expanded, top_k=20)
    if not candidates:
        first = list(books.values())[0]["text"]
        return first[:MAX_CONTEXT_CHARS], [list(books.keys())[0]]

    reranked = []
    for bm25_score, idx in candidates:
        chunk_text, fname = all_chunks[idx]
        # Re-rank với cả query gốc lẫn expanded
        bonus = exact_match_bonus(query, chunk_text) + exact_match_bonus(expanded, chunk_text)
        final_score = bm25_score + bonus
        reranked.append((final_score, chunk_text, fname))
    reranked.sort(key=lambda x: x[0], reverse=True)

    context, sources, used = "", [], 0
    for _, chunk, fname in reranked[:TOP_K_CHUNKS]:
        if used + len(chunk) > MAX_CONTEXT_CHARS:
            break
        context += f"\n[📕 {fname}]\n{chunk}\n"
        used    += len(chunk)
        if fname not in sources:
            sources.append(fname)

    return context.strip(), sources

# ============================================================
# 4. SYSTEM PROMPT
# ============================================================
_PERSONA = """Bạn là thầy Minh — giáo viên Tin học cấp 2 với hơn 20 năm đứng lớp tại trường THCS.
Bạn đã dạy qua hàng nghìn học sinh, từng là tổ trưởng tổ Tin học, và rất yêu nghề.
Xưng "thầy", gọi học sinh là "em". Ngôn ngữ gần gũi, ấm áp.
Chỉ trả lời về môn Tin học cấp 2. Nếu hỏi môn khác → từ chối thân thiện:
  "Thầy chỉ dạy Tin thôi em ơi, câu đó em hỏi thầy/cô chuyên môn khác nhé 😊"
Dùng emoji vừa phải: 💡 quan trọng · ✅ kết luận · ⚠️ lưu ý."""

def _book_section(context: str) -> str:
    if context:
        return f"""NỘI DUNG SÁCH GIÁO KHOA LIÊN QUAN (ưu tiên dùng phần này):
---
{context}
---"""
    return "Chưa có sách giáo khoa. Dùng kiến thức chuyên môn Tin học chuẩn."


def build_system_prompt(context: str, has_books: bool, mode: str = "direct") -> str:
    book = _book_section(context)

    if mode == "socratic":
        return f"""{_PERSONA}

{book}

CHẾ ĐỘ DẠY HỌC: SOCRATIC — THẦY HỎI, TRÒ TỰ KHÁM PHÁ
─────────────────────────────────────────────────────────────
Triết lý: Học sinh hiểu sâu hơn khi TỰ tìm ra câu trả lời.

✦ QUY TẮC CỐT LÕI:
   ❌ KHÔNG bao giờ trả lời thẳng câu hỏi lý thuyết/bài tập ngay lần đầu.
   ❌ KHÔNG dùng cụm "Câu trả lời là...", "Đáp án là...", "Kết quả là..."
   ✅ LUÔN hỏi ngược lại ít nhất 1 câu trước khi giải thích thêm.
   ✅ Nếu học sinh trả lời SAI → khen nỗ lực, hỏi thêm để dẫn dắt đúng hướng.
   ✅ Nếu học sinh trả lời ĐÚNG → xác nhận, khen ngợi, mở rộng thêm.
   ✅ Nếu học sinh hỏi lại "Thầy cho em xin đáp án đi" sau 3 lần → lúc đó mới giải thích đầy đủ.

✦ LUỒNG HỘI THOẠI:
   Lượt 1 → Thầy hỏi ngược (kích hoạt kiến thức nền)
   Lượt 2 → Học sinh trả lời → Thầy phản hồi + hỏi sâu hơn
   Lượt 3 → Học sinh gần đúng → Thầy gợi ý nhỏ + hỏi chốt
   Lượt 4 → Học sinh đúng → Thầy xác nhận + giải thích ngắn + khen
   (Sau 3 lượt vẫn chưa ra → thầy giải thích đầy đủ)

✦ GIỌNG ĐIỆU:
   - Hào hứng, tò mò: "Ooh, em nghĩ sao về điều này?"
   - Kiên nhẫn khi học sinh sai: "Hmm, thú vị! Nhưng thầy muốn hỏi thêm..."
   - Vui mừng khi học sinh đúng: "Chính xác! Em đã tự tìm ra rồi đó! 🎉"
─────────────────────────────────────────────────────────────"""

    return f"""{_PERSONA}

{book}

CHẾ ĐỘ DẠY HỌC: GIẢI THÍCH TRỰC TIẾP
─────────────────────────────────────────────────────────────
✦ CÁCH GIẢI THÍCH:
   - Bắt đầu bằng ví dụ thực tế đời thường TRƯỚC lý thuyết.
   - Dùng phép so sánh quen thuộc với học sinh cấp 2.
   - Giải thích từng bước nhỏ, không nhảy cóc.

✦ PHẢN HỒI & KHUYẾN KHÍCH:
   - Khen câu hỏi hay, hỏi sai hướng → nhẹ nhàng uốn nắn.
   - Cuối câu trả lời dài → hỏi lại: "Em hiểu đến đây chưa?"

✦ KINH NGHIỆM THỰC TẾ:
   - Kể tình huống lớp học, chỉ lỗi phổ biến, mẹo ghi nhớ.
─────────────────────────────────────────────────────────────"""

# ============================================================
# 5. GIAO DIỆN
# ============================================================
st.set_page_config(
    page_title="Thầy Minh - Giáo viên Tin học",
    layout="wide",
    page_icon="👨‍🏫",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .book-tag {
        display: inline-block; background: #e8f4fd; color: #1565c0;
        border-radius: 20px; padding: 2px 10px; font-size: 0.8em; margin: 2px;
    }
    .stat-card {
        background: #f0f2f6; border-radius: 8px;
        padding: 8px 12px; font-size: 0.85em; margin-bottom: 6px;
    }
    .teacher-badge {
        background: linear-gradient(135deg, #1565c0, #0d47a1);
        color: white; padding: 6px 14px; border-radius: 20px;
        font-size: 0.85em; font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 6. SIDEBAR
# ============================================================
with st.sidebar:
    st.title("⚙️ Cài đặt")

    # Danh sách sách
    st.subheader("📚 Sách đang dùng")
    books = load_all_books()
    if books:
        total_kc = sum(len(d["text"]) for d in books.values()) // 1000
        total_chunks = sum(len(d["chunks"]) for d in books.values())
        st.markdown(f'<div class="stat-card">📄 {len(books)} sách · ~{total_kc}K ký tự · {total_chunks} đoạn chỉ mục</div>',
                    unsafe_allow_html=True)
        for fname in books:
            st.markdown(f'<span class="book-tag">📕 {fname}</span>', unsafe_allow_html=True)
    else:
        st.info("Chưa có sách. Đặt file PDF/TXT vào thư mục `data/`")

    st.divider()

    # Cài đặt TTS
    st.subheader("🔊 Giọng đọc")
    tts_enabled = st.toggle("Tự động đọc câu trả lời", value=True)
    tts_rate  = st.slider("Tốc độ đọc:", 0.5, 1.5, 0.9, 0.05,
                          help="0.5 = chậm, 1.0 = bình thường, 1.5 = nhanh")
    st.caption("⚙️ Google TTS tiếng Việt · Không cần API key")

    st.divider()

    # Cài đặt model
    st.subheader("🤖 Model")
    model = st.selectbox(
        "Chọn model:",
        ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"],
        help="70b: chất lượng cao | 8b: phản hồi nhanh"
    )
    # Độ tự nhiên mặc định = 1.0 (max)
    temperature = st.slider("Độ tự nhiên của câu trả lời:", 0.0, 1.0, 1.0, 0.05,
                            help="1.0 = tự nhiên tối đa, nghe như thầy thật ngoài đời")
    max_history = st.slider("Số tin nhắn gửi lên API:", 4, 20, 10, 2)

    st.divider()

    # Chế độ dạy học
    st.subheader("🎓 Chế độ dạy học")
    teaching_mode = st.radio(
        "Chọn cách thầy phản hồi:",
        options=["direct", "socratic"],
        format_func=lambda x: "📖 Giải thích thẳng" if x == "direct" else "🤔 Socratic — tự khám phá",
        index=0,
        help="Socratic: thầy hỏi ngược để học sinh tự tìm đáp án"
    )
    if teaching_mode == "socratic":
        st.info("💡 Chế độ Socratic: thầy sẽ hỏi ngược lại thay vì trả lời thẳng.")

    st.divider()
    if st.button("🗑️ Xóa lịch sử chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ============================================================
# 7. VÙNG CHAT
# ============================================================
st.title("👨‍🏫 Thầy Minh — Giáo viên Tin học")
st.markdown('<span class="teacher-badge">🎓 20+ năm kinh nghiệm · Chuyên Tin học cấp 2</span>',
            unsafe_allow_html=True)
mode_label = "📖 Giải thích thẳng" if teaching_mode == "direct" else "🤔 Socratic"
st.caption(f"Model: `{model}` · {mode_label} · Tìm kiếm ngữ cảnh thông minh")

st.write("")

if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    with st.chat_message("assistant", avatar="👨‍🏫"):
        source = f"{len(books)} cuốn sách giáo khoa" if books else "kiến thức chuyên môn của thầy"
        st.markdown(f"""
Chào em! 👋 Thầy là thầy Minh, giáo viên Tin học.

Thầy đã dạy môn này hơn 20 năm rồi, từ hồi máy tính còn dùng đĩa mềm đấy! 😄

Hôm nay thầy đang có {source} để hỗ trợ em.

{"🤔 Hôm nay thầy dùng **phương pháp Socratic** — thầy sẽ hỏi ngược lại để em tự khám phá nhé! Đừng chờ thầy cho đáp án liền — hãy suy nghĩ cùng thầy! 😄" if teaching_mode == "socratic" else "Em cứ hỏi thẳng vào vấn đề nhé!"}

**Thầy chuyên:**
- 💡 Giải thích khái niệm Tin học từ cơ bản đến nâng cao
- 💻 Hướng dẫn lập trình (Scratch, Python, Pascal...)
- 🔍 Tra cứu nội dung sách giáo khoa
- ✅ Ôn tập, luyện đề kiểm tra

Em hỏi đi, đừng ngại nhé!
        """)

for i, msg in enumerate(st.session_state.messages):
    avatar = "👨‍🏫" if msg["role"] == "assistant" else "🧑‍🎓"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("mode") == "socratic":
            st.caption("🤔 Socratic mode")
        if msg["role"] == "assistant" and tts_enabled:
            msg_id = hashlib.md5(msg["content"][:80].encode()).hexdigest()[:8] + str(i)
            tts_widget(msg["content"], msg_id=msg_id, rate=tts_rate)

# ============================================================
# 8. XỬ LÝ CÂU HỎI
# ============================================================
if prompt := st.chat_input("Em hỏi thầy Minh nhé..."):

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍🎓"):
        st.markdown(prompt)

    with st.spinner("📚 Thầy đang tra cứu sách..."):
        context, sources = find_relevant_context(prompt, books)

    system_prompt = build_system_prompt(context, bool(books), mode=teaching_mode)

    with st.chat_message("assistant", avatar="👨‍🏫"):
        placeholder = st.empty()
        full_response = ""

        try:
            stream = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    *[{"role": m["role"], "content": m["content"]}
                      for m in st.session_state.messages[-max_history:]]
                ],
                model=model,
                temperature=temperature,
                max_tokens=1500,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_response += delta
                    placeholder.markdown(full_response + "▌")

            placeholder.markdown(full_response)

            if tts_enabled and full_response and not full_response.startswith("[Lỗi"):
                msg_id = hashlib.md5(full_response[:80].encode()).hexdigest()[:8]
                tts_widget(full_response, msg_id=msg_id, rate=tts_rate)

            if context and sources:
                label = f"📖 Nguồn: {', '.join(sources)}"
                with st.expander(label, expanded=False):
                    for src in sources:
                        st.markdown(f"📕 **{src}**")

        except Exception as e:
            err = str(e)
            if "401" in err or "api_key" in err.lower():
                st.error("❌ API key không hợp lệ. Vui lòng kiểm tra lại.")
            elif "429" in err:
                st.error("⏳ Hệ thống đang bận. Em thử lại sau vài giây nhé!")
            elif "model" in err.lower():
                st.error(f"❌ Model `{model}` không khả dụng. Thử chọn model khác.")
            else:
                st.error(f"❌ Lỗi: {err}")
            full_response = f"[Lỗi: {err}]"

        st.session_state.messages.append({
            "role": "assistant",
            "content": full_response,
            "mode": teaching_mode
        })