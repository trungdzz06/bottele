import logging
import re
import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.error import RetryAfter, BadRequest  # Thêm 2 thư viện xử lý lỗi API

# --- CẤU HÌNH ---
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = '8476342669:AAFHw-XXrgV9F6a1x06GHSKJh9peKhSc_2A'
MY_USER_ID = 1826158696
DB_FILE = "sent_links.txt"

# Regex V7: Bắt trọn vẹn mọi định dạng link
PATTERN = r'(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([a-zA-Z0-9_-]+)|(@[a-zA-Z0-9_]+)'

sent_links = set()
link_queue = asyncio.Queue()

def load_database():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if item: sent_links.add(item)
        print(f"📂 Đã nạp {len(sent_links)} link từ dữ liệu cũ.")

def save_to_database(raw_id):
    with open(DB_FILE, "a", encoding="utf-8") as f:
        f.write(raw_id + "\n")

# ==========================================
# 1. HÀM NHẬN TIN NHẮN VÀ XẾP HÀNG
# ==========================================
async def receive_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    matches = re.finditer(PATTERN, text)
    
    group_name = update.message.chat.title
    user_sender = update.message.from_user.full_name

    for m in matches:
        found = m.group(0)
        # Bóc tách lấy ID thuần túy (VD: adsfacebooks)
        raw_id = m.group(1) if m.group(1) else m.group(2).replace('@', '')
        
        if raw_id not in sent_links:
            sent_links.add(raw_id)
            save_to_database(raw_id)
            await link_queue.put((context, found, raw_id, group_name, user_sender))

# ==========================================
# 2. CÔNG NHÂN XỬ LÝ (KIỂM TRA CHẮC CHẮN MỚI GỬI)
# ==========================================
async def background_worker():
    while True:
        context, found, raw_id, group_name, user_sender = await link_queue.get()
        
        try:
            report_msg = None
            
            # Xử lý Link kín (Chắc chắn 100% là nhóm)
            if "+" in found or "joinchat" in found:
                report_msg = f"📩 **PHÁT HIỆN NHÓM KÍN!**\n👥 Nguồn: `{group_name}` | 👤 Gửi: {user_sender}\n🔗 [Bấm để vào nhóm]({found})"
            
            # Xử lý Link công khai / Username
            else:
                # Vòng lặp KIÊN TRÌ: Thử cho đến khi có kết quả
                while True:
                    try:
                        chat_info = await context.bot.get_chat(f"@{raw_id}")
                        # CHỈ CHỌN NHÓM VÀ KÊNH
                        if chat_info.type in ['group', 'supergroup', 'channel']:
                            label = "👥 Nhóm" if "group" in chat_info.type else "📢 Kênh"
                            report_msg = f"📩 **PHÁT HIỆN {label.upper()} MỚI!**\n👥 Nguồn: `{group_name}` | 👤 Gửi: {user_sender}\n{label}: [{found}](https://t.me/{raw_id})"
                        
                        # Đã check thành công (dù là Nhóm hay User) thì thoát vòng lặp
                        break 
                        
                    except RetryAfter as e:
                        # NẾU BỊ CHẶN: Đợi đúng số giây Telegram yêu cầu rồi tự động quay lại kiểm tra tiếp
                        print(f"⏳ Bot bị nghẽn. Đang đợi {e.retry_after} giây để kiểm tra lại {raw_id}...")
                        await asyncio.sleep(e.retry_after)
                        
                    except BadRequest:
                        # NẾU LÀ USER CÁ NHÂN HOẶC LINK HỎNG: Bỏ qua hoàn toàn, im lặng
                        print(f"ℹ️ {raw_id} là User cá nhân hoặc link hỏng -> Hủy bỏ.")
                        break 
                        
                    except Exception as e:
                        print(f"⚠️ Lỗi không xác định với {raw_id}: {e}")
                        break

            # CHỈ KHI NÀO report_msg CÓ NỘI DUNG (Là Nhóm) THÌ MỚI GỬI TIN NHẮN
            if report_msg:
                await context.bot.send_message(chat_id=MY_USER_ID, text=report_msg, parse_mode='Markdown', disable_web_page_preview=True)
                print(f"✅ Đã gửi báo cáo cho: {raw_id}")

        except Exception as e:
            print(f"❌ Lỗi Worker: {e}")
        
        finally:
            link_queue.task_done()
            await asyncio.sleep(2) # Nghỉ ngơi 2s giữa các lần check

# ==========================================
# 3. KHỞI ĐỘNG HỆ THỐNG
# ==========================================
async def post_init(application: ApplicationBuilder):
    # Khởi động công nhân chạy ngầm
    asyncio.create_task(background_worker())

if __name__ == '__main__':
    load_database()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), receive_links))
    
    print("Bot 'Kiểm Tra Chắc Chắn' đang chạy... Cam kết không gửi link rác!")
    app.run_polling()