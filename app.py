import os
import html
import random
import string
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
import psycopg2
import cloudinary
import cloudinary.uploader
import gradio as gr

# --- Configuration ---
DATABASE_URL = os.environ.get("DATABASE_URL")
IST = ZoneInfo("Asia/Kolkata")

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)

# Separate private passwords/PINs for each friend
PRESET_FRIENDS = [
    ("PRATYUSH-01", "Pratyush", "PRAT@7821"),
    ("MRIDUL-01", "Mridul", "MRID@4519"),
    ("VERMA-01", "Verma", "VERM@9034"),
    ("LAKSHITA-01", "Lakshita", "LAKS@6182"),
    ("ISIKA-01", "Isika", "ISIK@3497"),
]

GROUP_CHAT_ID = "SQUAD-GROUP"
GROUP_CHAT_LABEL = "Squad Group (All 5)"
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")


# --- Helpers ---
def now_ist() -> datetime:
    return datetime.now(IST)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode("utf-8")).hexdigest()


def generate_unique_id() -> str:
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choices(chars, k=5))
    return f"FRIEND-{code}"


def is_video_url(url: str) -> bool:
    if not url:
        return False
    clean_url = url.split("?")[0].lower()
    return "/video/upload/" in clean_url or clean_url.endswith(VIDEO_EXTENSIONS)


def get_avatar_color(name: str) -> str:
    gradients = [
        "linear-gradient(135deg, #6366f1, #8b5cf6)",
        "linear-gradient(135deg, #ec4899, #f43f5e)",
        "linear-gradient(135deg, #10b981, #059669)",
        "linear-gradient(135deg, #f59e0b, #ea580c)",
        "linear-gradient(135deg, #06b6d4, #2563eb)",
    ]
    return gradients[sum(ord(c) for c in name) % len(gradients)]


# --- Database Setup ---
def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            pin_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            user_id TEXT NOT NULL,
            friend_id TEXT NOT NULL,
            PRIMARY KEY (user_id, friend_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender_id TEXT NOT NULL,
            receiver_id TEXT NOT NULL,
            content TEXT,
            image_url TEXT,
            created_at TEXT NOT NULL
        )
    """)

    timestamp = now_ist().strftime("%b %d, %Y")
    for uid, name, private_pin in PRESET_FRIENDS:
        cursor.execute(
            """
            INSERT INTO users (user_id, display_name, pin_hash, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                pin_hash = EXCLUDED.pin_hash
            """,
            (uid, name, hash_pin(private_pin), timestamp),
        )

    for uid_a, _, _ in PRESET_FRIENDS:
        for uid_b, _, _ in PRESET_FRIENDS:
            if uid_a != uid_b:
                cursor.execute(
                    "INSERT INTO friends (user_id, friend_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (uid_a, uid_b),
                )

    conn.commit()
    cursor.close()
    conn.close()


# --- Auth & Friend Management ---
def create_account(display_name: str, pin: str, custom_id: str = ""):
    if not display_name or not display_name.strip():
        return None, "Please enter a name."
    if not pin or len(pin.strip()) < 4:
        return None, "Please enter a password/PIN of at least 4 characters."

    clean_name = display_name.strip()
    clean_pin_hash = hash_pin(pin)
    timestamp = now_ist().strftime("%b %d, %Y")

    conn = get_connection()
    cursor = conn.cursor()

    if custom_id and custom_id.strip():
        chosen_id = custom_id.strip().upper()
        cursor.execute("SELECT 1 FROM users WHERE user_id = %s", (chosen_id,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return None, f"ID '{chosen_id}' is already taken."
    else:
        while True:
            chosen_id = generate_unique_id()
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s", (chosen_id,))
            if not cursor.fetchone():
                break

    cursor.execute(
        "INSERT INTO users (user_id, display_name, pin_hash, created_at) VALUES (%s, %s, %s, %s)",
        (chosen_id, clean_name, clean_pin_hash, timestamp),
    )

    for preset_id, _, _ in PRESET_FRIENDS:
        if chosen_id != preset_id:
            cursor.execute(
                "INSERT INTO friends (user_id, friend_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (chosen_id, preset_id),
            )
            cursor.execute(
                "INSERT INTO friends (user_id, friend_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (preset_id, chosen_id),
            )

    conn.commit()
    cursor.close()
    conn.close()
    return chosen_id, f"Created ID {chosen_id} for {clean_name}!"


def login_account(user_id: str, pin: str):
    if not user_id or not pin:
        return None, None, "Enter both your Friend ID and Password."

    clean_id = user_id.strip().upper()
    clean_pin_hash = hash_pin(pin)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT display_name, pin_hash FROM users WHERE user_id = %s",
        (clean_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return None, None, "Friend ID not found."
    if row[1] != clean_pin_hash:
        return None, None, "Incorrect Password/PIN."

    return clean_id, row[0], f"Welcome, {row[0]}!"


def update_user_pin(user_id: str, new_pin: str):
    if not user_id:
        return "Not logged in."
    if not new_pin or len(new_pin.strip()) < 4:
        return "New password must be at least 4 characters."

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET pin_hash = %s WHERE user_id = %s",
        (hash_pin(new_pin), user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return "Password updated successfully!"


def add_friend_by_id(current_user_id: str, target_friend_id: str):
    if not current_user_id:
        return "Not logged in."
    if not target_friend_id or not target_friend_id.strip():
        return "Enter a Friend ID."

    clean_target = target_friend_id.strip().upper()
    if clean_target == current_user_id:
        return "You cannot add yourself."

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT display_name FROM users WHERE user_id = %s", (clean_target,))
    target_user = cursor.fetchone()
    if not target_user:
        cursor.close()
        conn.close()
        return f"No user found with ID '{clean_target}'."

    cursor.execute(
        "INSERT INTO friends (user_id, friend_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (current_user_id, clean_target),
    )
    cursor.execute(
        "INSERT INTO friends (user_id, friend_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (clean_target, current_user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return f"Added {target_user[0]} ({clean_target})!"


def get_contact_choices(current_user_id: str):
    if not current_user_id:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.display_name, u.user_id
        FROM friends f
        JOIN users u ON f.friend_id = u.user_id
        WHERE f.user_id = %s
        ORDER BY u.display_name ASC
        """,
        (current_user_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    contacts = [f"👥 {GROUP_CHAT_LABEL}"]
    contacts.extend([f"💬 {name} ({fid})" for name, fid in rows])
    return contacts


def extract_target_id(choice_str: str) -> str:
    if not choice_str:
        return ""
    if GROUP_CHAT_LABEL in choice_str:
        return GROUP_CHAT_ID
    if "(" in choice_str and choice_str.endswith(")"):
        return choice_str.split("(")[-1][:-1].strip()
    return ""


# --- Messaging & Media ---
def upload_media(file_path):
    if not file_path:
        return None
    result = cloudinary.uploader.upload(file_path, resource_type="auto")
    return result.get("secure_url")


def send_message(sender_id: str, contact_choice: str, text: str, file_path):
    target_id = extract_target_id(contact_choice)
    if not sender_id or not target_id:
        return "Select a chat first."

    has_text = bool(text and text.strip())
    has_media = bool(file_path)
    if not has_text and not has_media:
        return "Type a message or attach a photo, GIF, or video."

    clean_text = text.strip() if has_text else ""
    image_url = upload_media(file_path) if has_media else None
    timestamp = now_ist().strftime("%I:%M %p • %d %b")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO messages (sender_id, receiver_id, content, image_url, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (sender_id, target_id, clean_text, image_url, timestamp),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return ""


def render_chat_header(contact_choice: str) -> str:
    if not contact_choice:
        return '<div class="chat-top-bar"><span>Select a conversation</span></div>'

    target_id = extract_target_id(contact_choice)
    if target_id == GROUP_CHAT_ID:
        return """
        <div class="chat-top-bar">
            <div class="chat-avatar" style="background: linear-gradient(135deg, #00a884, #0284c7);">👥</div>
            <div class="chat-title-wrap">
                <div class="chat-title">Squad Group</div>
                <div class="chat-subtitle">Pratyush, Mridul, Verma, Lakshita, Isika</div>
            </div>
        </div>
        """

    clean_label = contact_choice.replace("💬 ", "")
    name_only = clean_label.split("(")[0].strip()
    initial = html.escape(name_only[0].upper()) if name_only else "?"
    bg = get_avatar_color(name_only)

    return f"""
    <div class="chat-top-bar">
        <div class="chat-avatar" style="background: {bg};">{initial}</div>
        <div class="chat-title-wrap">
            <div class="chat-title">{html.escape(name_only)}</div>
            <div class="chat-subtitle">{html.escape(target_id)} • Online</div>
        </div>
    </div>
    """


def render_chat_history(current_user_id: str, contact_choice: str) -> str:
    target_id = extract_target_id(contact_choice)
    if not current_user_id or not target_id:
        return '<div class="empty-chat">Select a friend from the left panel to start chatting.</div>'

    conn = get_connection()
    cursor = conn.cursor()

    if target_id == GROUP_CHAT_ID:
        cursor.execute(
            """
            SELECT m.sender_id, COALESCE(u.display_name, m.sender_id), m.content, m.image_url, m.created_at
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.user_id
            WHERE m.receiver_id = %s
            ORDER BY m.id ASC
            """,
            (GROUP_CHAT_ID,),
        )
    else:
        cursor.execute(
            """
            SELECT m.sender_id, COALESCE(u.display_name, m.sender_id), m.content, m.image_url, m.created_at
            FROM messages m
            LEFT JOIN users u ON m.sender_id = u.user_id
            WHERE (m.sender_id = %s AND m.receiver_id = %s)
               OR (m.sender_id = %s AND m.receiver_id = %s)
            ORDER BY m.id ASC
            """,
            (current_user_id, target_id, target_id, current_user_id),
        )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return '<div class="empty-chat">No messages yet. Say hi or send a photo, GIF, or video!</div>'

    bubbles = ['<div class="chat-scroll-area" id="chat-feed">']
    for sender_id, sender_name, content, image_url, created_at in rows:
        is_me = sender_id == current_user_id
        row_cls = "msg-row-me" if is_me else "msg-row-them"
        bubble_cls = "bubble-me" if is_me else "bubble-them"

        sender_tag = ""
        if target_id == GROUP_CHAT_ID and not is_me:
            sender_tag = f'<div class="group-sender">{html.escape(sender_name)}</div>'

        text_html = ""
        if content:
            safe_text = html.escape(content).replace("\n", "<br>")
            text_html = f'<div class="msg-text">{safe_text}</div>'

        media_html = ""
        if image_url:
            safe_url = html.escape(image_url)
            if is_video_url(image_url):
                media_html = f"""
                <video class="msg-video" controls playsinline preload="metadata">
                    <source src="{safe_url}">
                </video>
                """
            else:
                media_html = f'<img class="msg-media" src="{safe_url}" alt="Media" loading="lazy" />'

        ticks = '<span class="ticks">✓✓</span>' if is_me else ""
        bubbles.append(f"""
        <div class="{row_cls}">
            <div class="{bubble_cls}">
                {sender_tag}
                {text_html}
                {media_html}
                <div class="msg-meta">{created_at} {ticks}</div>
            </div>
        </div>
        """)
    bubbles.append("</div>")
    return "".join(bubbles)


# --- Sleek WhatsApp / Instagram DM CSS ---
CUSTOM_CSS = """
.gradio-container {
    max-width: 1120px !important;
    margin: 0 auto !important;
    padding: 12px 16px !important;
}
footer { display: none !important; }

.auth-wrapper {
    max-width: 440px !important;
    margin: 36px auto !important;
    background: var(--background-fill-primary);
    border: 1px solid var(--border-color-primary);
    border-radius: 18px;
    padding: 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.08);
}
.brand-header {
    text-align: center;
    margin-bottom: 14px;
}

.messenger-shell {
    border: 1px solid var(--border-color-primary);
    border-radius: 16px;
    overflow: hidden;
    background: var(--background-fill-primary);
    box-shadow: 0 8px 28px rgba(0,0,0,0.07);
}
.sidebar-col {
    border-right: 1px solid var(--border-color-primary);
    background: var(--background-fill-primary);
    padding: 12px !important;
}
.profile-strip {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 10px;
    background: var(--background-fill-secondary);
    border-radius: 12px;
    margin-bottom: 10px;
}
.profile-name {
    font-weight: 700;
    font-size: 0.95rem;
}
.profile-id {
    font-size: 0.75rem;
    opacity: 0.75;
}

.contact-list .wrap {
    display: flex !important;
    flex-direction: column !important;
    gap: 6px !important;
}
.contact-list label {
    border-radius: 12px !important;
    padding: 11px 14px !important;
    border: 1px solid transparent !important;
    background: var(--background-fill-secondary) !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}
.contact-list label:hover {
    border-color: var(--border-color-accent) !important;
}
.contact-list label.selected {
    background: #00a884 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}

.chat-col {
    padding: 0 !important;
    display: flex;
    flex-direction: column;
}
.chat-top-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 18px;
    background: var(--background-fill-secondary);
    border-bottom: 1px solid var(--border-color-primary);
}
.chat-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    color: white;
    font-weight: 700;
    font-size: 1.05rem;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.chat-title {
    font-weight: 700;
    font-size: 1rem;
    line-height: 1.2;
}
.chat-subtitle {
    font-size: 0.78rem;
    opacity: 0.72;
}

.chat-scroll-area {
    height: 470px;
    overflow-y: auto;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: var(--background-fill-primary);
}
.msg-row-me {
    display: flex;
    justify-content: flex-end;
}
.msg-row-them {
    display: flex;
    justify-content: flex-start;
}
.bubble-me {
    background: #005c4b;
    color: #ffffff;
    padding: 9px 13px;
    border-radius: 14px 14px 2px 14px;
    max-width: 72%;
    box-shadow: 0 1px 2px rgba(0,0,0,0.12);
    word-wrap: break-word;
}
.bubble-them {
    background: var(--background-fill-secondary);
    color: var(--body-text-color);
    border: 1px solid var(--border-color-primary);
    padding: 9px 13px;
    border-radius: 14px 14px 14px 2px;
    max-width: 72%;
    box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    word-wrap: break-word;
}
.group-sender {
    font-size: 0.74rem;
    font-weight: 700;
    color: #00a884;
    margin-bottom: 3px;
}
.msg-text {
    font-size: 0.94rem;
    line-height: 1.42;
}
.msg-media, .msg-video {
    max-width: 100%;
    max-height: 290px;
    border-radius: 10px;
    margin-top: 5px;
    display: block;
    background: #000;
}
.msg-meta {
    font-size: 0.68rem;
    opacity: 0.75;
    margin-top: 4px;
    text-align: right;
}
.ticks {
    color: #53bdeb;
    font-weight: 700;
    margin-left: 3px;
}
.empty-chat {
    height: 470px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 24px;
    color: var(--body-text-color-subdued);
    font-size: 0.95rem;
}

.composer-bar {
    padding: 10px 14px;
    background: var(--background-fill-secondary);
    border-top: 1px solid var(--border-color-primary);
    align-items: center !important;
}
.drawer-panel {
    padding: 10px 14px;
    background: var(--background-fill-secondary);
    border-top: 1px solid var(--border-color-primary);
}
"""

init_db()

with gr.Blocks(title="WhisperChat") as demo:
    current_user_id = gr.State(None)
    current_user_name = gr.State(None)
    attach_open = gr.State(False)
    add_box_open = gr.State(False)
    pin_box_open = gr.State(False)

    with gr.Column(elem_classes="auth-wrapper") as auth_section:
        gr.Markdown(
            """<div class="brand-header"><h2>💬 WhisperChat</h2><p style="opacity:0.75;font-size:0.9rem;">Private Squad Messenger</p></div>"""
        )
        with gr.Tabs():
            with gr.Tab("Log In"):
                login_id = gr.Textbox(label="Friend ID", placeholder="e.g., PRATYUSH-01")
                login_pin = gr.Textbox(label="Password / PIN", type="password", placeholder="Enter your private PIN")
                login_btn = gr.Button("Log In", variant="primary", size="lg")

            with gr.Tab("Create New ID"):
                reg_name = gr.Textbox(label="Friend's Name", placeholder="e.g., Rohan")
                reg_pin = gr.Textbox(label="Set Private PIN", type="password", placeholder="Min 4 characters")
                reg_custom_id = gr.Textbox(label="Custom ID (Optional)", placeholder="Leave blank for auto ID")
                reg_btn = gr.Button("Generate ID & Enter", variant="primary", size="lg")

    with gr.Group(visible=False, elem_classes="messenger-shell") as chat_section:
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=270, elem_classes="sidebar-col"):
                profile_html = gr.HTML("")

                with gr.Row():
                    toggle_add_btn = gr.Button("➕ Add ID", size="sm")
                    toggle_pin_btn = gr.Button("🔑 PIN", size="sm")
                    logout_btn = gr.Button("🚪 Exit", size="sm")

                with gr.Group(visible=False) as add_friend_drawer:
                    with gr.Row():
                        friend_id_input = gr.Textbox(show_label=False, placeholder="Friend ID...", scale=3)
                        add_friend_btn = gr.Button("Add", variant="primary", scale=1, min_width=60)

                with gr.Group(visible=False) as change_pin_drawer:
                    with gr.Row():
                        new_pin_input = gr.Textbox(show_label=False, placeholder="New PIN...", type="password", scale=3)
                        save_pin_btn = gr.Button("Save", variant="primary", scale=1, min_width=65)

                friend_selector = gr.Radio(
                    choices=[],
                    show_label=False,
                    interactive=True,
                    elem_classes="contact-list",
                )

            with gr.Column(scale=2, elem_classes="chat-col"):
                chat_header_html = gr.HTML(render_chat_header(None))
                chat_display_html = gr.HTML(render_chat_history(None, None))

                with gr.Group(visible=False, elem_classes="drawer-panel") as attach_drawer:
                    media_input = gr.File(
                        label="Attach Photo, GIF, or Video",
                        file_types=[".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".m4v"],
                        type="filepath",
                    )

                with gr.Row(elem_classes="composer-bar"):
                    attach_toggle_btn = gr.Button("📎", scale=0, min_width=46)
                    msg_input = gr.Textbox(
                        show_label=False,
                        placeholder="Type a message...",
                        lines=1,
                        max_lines=3,
                        scale=5,
                        container=False,
                    )
                    send_btn = gr.Button("➤", variant="primary", scale=0, min_width=54)

    live_timer = gr.Timer(value=3, active=False)

    def build_profile_card(uid, uname):
        return f"""
        <div class="profile-strip">
            <div>
                <div class="profile-name">🟢 {html.escape(uname)}</div>
                <div class="profile-id">ID: <code>{html.escape(uid)}</code></div>
            </div>
        </div>
        """

    def enter_app(uid, uname):
        contacts = get_contact_choices(uid)
        default_chat = contacts[0] if contacts else None
        return (
            uid,
            uname,
            gr.update(visible=False),
            gr.update(visible=True),
            build_profile_card(uid, uname),
            gr.update(choices=contacts, value=default_chat),
            render_chat_header(default_chat),
            render_chat_history(uid, default_chat),
            gr.Timer(active=True),
        )

    def handle_login(uid, pin):
        valid_id, uname, msg = login_account(uid, pin)
        if not valid_id:
            gr.Warning(msg)
            return (
                None, None, gr.update(visible=True), gr.update(visible=False),
                "", gr.update(), gr.update(), gr.update(), gr.Timer(active=False)
            )
        gr.Info(msg)
        return enter_app(valid_id, uname)

    def handle_register(name, pin, custom_id):
        new_id, msg = create_account(name, pin, custom_id)
        if not new_id:
            gr.Warning(msg)
            return (
                None, None, gr.update(visible=True), gr.update(visible=False),
                "", gr.update(), gr.update(), gr.update(), gr.Timer(active=False)
            )
        gr.Info(msg)
        return enter_app(new_id, name.strip())

    def handle_logout():
        return (
            None,
            None,
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            gr.update(choices=[], value=None),
            render_chat_header(None),
            render_chat_history(None, None),
            gr.Timer(active=False),
        )

    def toggle_flag(flag_val):
        new_val = not flag_val
        return new_val, gr.update(visible=new_val)

    def handle_add_friend(uid, target_id):
        status = add_friend_by_id(uid, target_id)
        if "Added" in status:
            gr.Info(status)
        else:
            gr.Warning(status)
        contacts = get_contact_choices(uid)
        clean_target = target_id.strip().upper() if target_id else ""
        selected = next((c for c in contacts if f"({clean_target})" in c), contacts[0] if contacts else None)
        return (
            "",
            False,
            gr.update(visible=False),
            gr.update(choices=contacts, value=selected),
            render_chat_header(selected),
            render_chat_history(uid, selected),
        )

    def handle_save_pin(uid, new_pin):
        msg = update_user_pin(uid, new_pin)
        if "successfully" in msg:
            gr.Info(msg)
            return "", False, gr.update(visible=False)
        gr.Warning(msg)
        return gr.update(), True, gr.update(visible=True)

    def handle_select_chat(uid, selected_contact):
        return render_chat_header(selected_contact), render_chat_history(uid, selected_contact)

    def handle_send(uid, selected_contact, text, media_file):
        try:
            err = send_message(uid, selected_contact, text, media_file)
        except Exception as e:
            gr.Error(f"Upload failed: {str(e)}")
            return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

        if err:
            gr.Warning(err)
            return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

        return (
            "",
            None,
            False,
            gr.update(visible=False),
            render_chat_history(uid, selected_contact),
        )

    def poll_messages(uid, selected_contact):
        if not uid or not selected_contact:
            return gr.update()
        return render_chat_history(uid, selected_contact)

    login_btn.click(
        fn=handle_login,
        inputs=[login_id, login_pin],
        outputs=[
            current_user_id, current_user_name, auth_section, chat_section,
            profile_html, friend_selector, chat_header_html, chat_display_html, live_timer
        ],
    )

    reg_btn.click(
        fn=handle_register,
        inputs=[reg_name, reg_pin, reg_custom_id],
        outputs=[
            current_user_id, current_user_name, auth_section, chat_section,
            profile_html, friend_selector, chat_header_html, chat_display_html, live_timer
        ],
    )

    logout_btn.click(
        fn=handle_logout,
        outputs=[
            current_user_id, current_user_name, auth_section, chat_section,
            profile_html, friend_selector, chat_header_html, chat_display_html, live_timer
        ],
    )

    attach_toggle_btn.click(fn=toggle_flag, inputs=[attach_open], outputs=[attach_open, attach_drawer])
    toggle_add_btn.click(fn=toggle_flag, inputs=[add_box_open], outputs=[add_box_open, add_friend_drawer])
    toggle_pin_btn.click(fn=toggle_flag, inputs=[pin_box_open], outputs=[pin_box_open, change_pin_drawer])

    add_friend_btn.click(
        fn=handle_add_friend,
        inputs=[current_user_id, friend_id_input],
        outputs=[friend_id_input, add_box_open, add_friend_drawer, friend_selector, chat_header_html, chat_display_html],
    )

    save_pin_btn.click(
        fn=handle_save_pin,
        inputs=[current_user_id, new_pin_input],
        outputs=[new_pin_input, pin_box_open, change_pin_drawer],
    )

    friend_selector.change(
        fn=handle_select_chat,
        inputs=[current_user_id, friend_selector],
        outputs=[chat_header_html, chat_display_html],
    )

    send_btn.click(
        fn=handle_send,
        inputs=[current_user_id, friend_selector, msg_input, media_input],
        outputs=[msg_input, media_input, attach_open, attach_drawer, chat_display_html],
    )

    msg_input.submit(
        fn=handle_send,
        inputs=[current_user_id, friend_selector, msg_input, media_input],
        outputs=[msg_input, media_input, attach_open, attach_drawer, chat_display_html],
    )

    live_timer.tick(
        fn=poll_messages,
        inputs=[current_user_id, friend_selector],
        outputs=[chat_display_html],
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        theme=gr.themes.Soft(primary_hue="emerald", neutral_hue="slate"),
        css=CUSTOM_CSS,
    )
