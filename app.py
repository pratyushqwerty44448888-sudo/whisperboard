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

PRESET_FRIENDS = [
    ("PRATYUSH-01", "Pratyush", "1234"),
    ("MRIDUL-01", "Mridul", "1234"),
    ("VERMA-01", "Verma", "1234"),
    ("LAKSHITA-01", "Lakshita", "1234"),
    ("ISIKA-01", "Isika", "1234"),
]

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")


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
    for uid, name, default_pin in PRESET_FRIENDS:
        cursor.execute(
            """
            INSERT INTO users (user_id, display_name, pin_hash, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (uid, name, hash_pin(default_pin), timestamp),
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


def create_account(display_name: str, pin: str, custom_id: str = ""):
    if not display_name or not display_name.strip():
        return None, "Please enter your friend's name."
    if not pin or len(pin.strip()) < 4:
        return None, "Please enter a PIN of at least 4 characters."

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
            return None, f"ID '{chosen_id}' already exists. Pick another or leave blank."
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
    return chosen_id, f"Generated ID for {clean_name}: {chosen_id} (PIN: {pin.strip()})"


def login_account(user_id: str, pin: str):
    if not user_id or not pin:
        return None, None, "Enter both your Friend ID and PIN."

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
        return None, None, "Incorrect PIN."

    return clean_id, row[0], f"Logged in as {row[0]} ({clean_id})"


def add_friend_by_id(current_user_id: str, target_friend_id: str):
    if not current_user_id:
        return "You must be logged in."
    if not target_friend_id or not target_friend_id.strip():
        return "Enter a Friend ID to add."

    clean_target = target_friend_id.strip().upper()
    if clean_target == current_user_id:
        return "You cannot add your own ID."

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


def get_friend_choices(current_user_id: str):
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
        ORDER BY
            CASE WHEN u.user_id = 'PRATYUSH-01' THEN 0 ELSE 1 END,
            u.display_name ASC
        """,
        (current_user_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [f"{name} ({fid})" for name, fid in rows]


def extract_id_from_choice(choice_str: str) -> str:
    if not choice_str or "(" not in choice_str or not choice_str.endswith(")"):
        return ""
    return choice_str.split("(")[-1][:-1].strip()


def upload_media(file_path):
    if not file_path:
        return None
    result = cloudinary.uploader.upload(file_path, resource_type="auto")
    return result.get("secure_url")


def send_direct_message(sender_id: str, friend_choice: str, text: str, file_path):
    receiver_id = extract_id_from_choice(friend_choice)
    if not sender_id or not receiver_id:
        return "Select a friend first."

    has_text = bool(text and text.strip())
    has_media = bool(file_path)
    if not has_text and not has_media:
        return "Type a message or attach an image, GIF, or video."

    clean_text = text.strip() if has_text else ""
    image_url = upload_media(file_path) if has_media else None
    timestamp = now_ist().strftime("%b %d • %I:%M %p IST")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO messages (sender_id, receiver_id, content, image_url, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (sender_id, receiver_id, clean_text, image_url, timestamp),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return ""


def render_chat_history(current_user_id: str, friend_choice: str):
    receiver_id = extract_id_from_choice(friend_choice)
    if not current_user_id:
        return '<div class="empty-chat">Log in with your Friend ID to start messaging.</div>'
    if not receiver_id:
        return '<div class="empty-chat">Select a friend from your list to start chatting!</div>'

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sender_id, content, image_url, created_at
        FROM messages
        WHERE (sender_id = %s AND receiver_id = %s)
           OR (sender_id = %s AND receiver_id = %s)
        ORDER BY id ASC
        """,
        (current_user_id, receiver_id, receiver_id, current_user_id),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return f'<div class="empty-chat">No messages with <b>{html.escape(friend_choice)}</b> yet. Send the first text, photo, GIF, or video!</div>'

    bubbles = ['<div class="chat-container">']
    for sender_id, content, image_url, created_at in rows:
        is_me = sender_id == current_user_id
        align_class = "msg-row-me" if is_me else "msg-row-them"
        bubble_class = "msg-bubble-me" if is_me else "msg-bubble-them"

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
                    Your browser does not support video playback.
                </video>
                """
            else:
                media_html = f'<img class="msg-media" src="{safe_url}" alt="Attachment" loading="lazy" />'

        bubbles.append(f"""
        <div class="{align_class}">
            <div class="{bubble_class}">
                {text_html}
                {media_html}
                <div class="msg-time">{created_at}</div>
            </div>
        </div>
        """)
    bubbles.append("</div>")
    return "".join(bubbles)


CUSTOM_CSS = """
.gradio-container {
    max-width: 960px !important;
    margin: 0 auto !important;
    padding-top: 20px !important;
}
.id-badge-box {
    background: var(--color-accent-soft);
    border: 1px solid var(--color-accent);
    border-radius: 10px;
    padding: 12px 16px;
    margin-bottom: 12px;
    font-size: 0.95rem;
}
.preset-box {
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    border-radius: 10px;
    padding: 12px 16px;
    margin-top: 10px;
    font-size: 0.9rem;
}
.chat-container {
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-height: 480px;
    overflow-y: auto;
    padding: 16px;
    border: 1px solid var(--border-color-primary);
    border-radius: 12px;
    background: var(--background-fill-secondary);
}
.msg-row-me {
    display: flex;
    justify-content: flex-end;
}
.msg-row-them {
    display: flex;
    justify-content: flex-start;
}
.msg-bubble-me {
    background: var(--color-accent);
    color: white;
    padding: 10px 14px;
    border-radius: 16px 16px 4px 16px;
    max-width: 72%;
    word-wrap: break-word;
}
.msg-bubble-them {
    background: var(--background-fill-primary);
    color: var(--body-text-color);
    border: 1px solid var(--border-color-primary);
    padding: 10px 14px;
    border-radius: 16px 16px 16px 4px;
    max-width: 72%;
    word-wrap: break-word;
}
.msg-text {
    font-size: 0.95rem;
    line-height: 1.45;
}
.msg-media, .msg-video {
    max-width: 100%;
    max-height: 300px;
    border-radius: 8px;
    margin-top: 6px;
    display: block;
    background: #000;
}
.msg-time {
    font-size: 0.72rem;
    opacity: 0.78;
    margin-top: 4px;
    text-align: right;
}
.empty-chat {
    text-align: center;
    padding: 60px 20px;
    border: 1px dashed var(--border-color-primary);
    border-radius: 12px;
    color: var(--body-text-color-subdued);
}
"""

init_db()

with gr.Blocks(title="WhisperChat — Friends Messenger") as demo:
    current_user_id = gr.State(None)
    current_user_name = gr.State(None)

    gr.Markdown("""# 💬 WhisperChat
*Log in with your Friend ID to send texts, photos, GIFs, and videos.*""")

    with gr.Group() as auth_section:
        with gr.Tabs():
            with gr.Tab("🔑 Log In with Your Friend ID"):
                gr.Markdown("Enter the **Friend ID** and **PIN** shared with you.")
                with gr.Row():
                    login_id = gr.Textbox(label="Your Friend ID", placeholder="e.g., MRIDUL-01")
                    login_pin = gr.Textbox(label="PIN", type="password", value="1234")
                login_btn = gr.Button("Open My Messages", variant="primary")

                gr.HTML("""
                <div class="preset-box">
                    <b>Pre-Generated Group IDs (Default PIN: <code>1234</code>):</b><br>
                    • <b>Pratyush:</b> <code>PRATYUSH-01</code> &nbsp;|&nbsp;
                    • <b>Mridul:</b> <code>MRIDUL-01</code> &nbsp;|&nbsp;
                    • <b>Verma:</b> <code>VERMA-01</code> &nbsp;|&nbsp;
                    • <b>Lakshita:</b> <code>LAKSHITA-01</code> &nbsp;|&nbsp;
                    • <b>Isika:</b> <code>ISIKA-01</code>
                </div>
                """)

            with gr.Tab("✨ Generate Extra Friend ID"):
                gr.Markdown("Generate a new Friend ID for someone else (automatically connects them to the whole group).")
                with gr.Row():
                    reg_name = gr.Textbox(label="Friend's Name", placeholder="e.g., Rohan")
                    reg_pin = gr.Textbox(label="Assign PIN", value="1234")
                reg_custom_id = gr.Textbox(
                    label="Custom ID (Optional — leave blank to auto-generate e.g. FRIEND-8X29A)",
                    placeholder="e.g., ROHAN-01",
                )
                reg_btn = gr.Button("Generate Friend ID & Log In", variant="primary")

    with gr.Group(visible=False) as chat_section:
        with gr.Row(equal_height=True):
            user_banner = gr.HTML("")
            logout_btn = gr.Button("🚪 Log Out", scale=0, min_width=110)

        with gr.Row():
            with gr.Column(scale=1, min_width=260):
                gr.Markdown("### 👥 Group Friends")
                friend_selector = gr.Radio(
                    choices=[],
                    label="Select who to message",
                    interactive=True,
                )
                refresh_friends_btn = gr.Button("🔄 Refresh Chat", size="sm")

                gr.Markdown("### ➕ Add Another ID")
                with gr.Row():
                    friend_id_input = gr.Textbox(
                        show_label=False,
                        placeholder="Enter ID...",
                        scale=3,
                    )
                    add_friend_btn = gr.Button("Add", variant="secondary", scale=1, min_width=65)

            with gr.Column(scale=2):
                chat_header = gr.Markdown("### Select a friend to start messaging")
                chat_display = gr.HTML(render_chat_history(None, None))

                with gr.Row():
                    msg_input = gr.Textbox(
                        show_label=False,
                        placeholder="Write a message...",
                        lines=2,
                        scale=4,
                    )
                    send_btn = gr.Button("Send ➤", variant="primary", scale=1, min_width=100)

                media_input = gr.File(
                    label="Attach Photo, GIF, or Video (PNG, JPG, WEBP, GIF, MP4, WebM, MOV)",
                    file_types=[".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".m4v"],
                    type="filepath",
                )

    def enter_app(uid, uname):
        friends = get_friend_choices(uid)
        default_friend = next((f for f in friends if "(PRATYUSH-01)" in f), friends[0] if friends else None)
        banner = f"""
        <div class="id-badge-box">
            Logged in as <b>{html.escape(uname)}</b> &nbsp;|&nbsp;
            Your Friend ID: <b><code>{html.escape(uid)}</code></b>
        </div>
        """
        header_text = f"### Chatting with {default_friend}" if default_friend else "### Select a friend to chat"
        return (
            uid,
            uname,
            gr.update(visible=False),
            gr.update(visible=True),
            banner,
            gr.update(choices=friends, value=default_friend),
            header_text,
            render_chat_history(uid, default_friend),
        )

    def handle_register(name, pin, custom_id):
        new_id, msg = create_account(name, pin, custom_id)
        if not new_id:
            gr.Warning(msg)
            return (
                None, None, gr.update(visible=True), gr.update(visible=False),
                "", gr.update(), gr.update(), gr.update()
            )
        gr.Info(msg)
        return enter_app(new_id, name.strip())

    def handle_login(uid, pin):
        valid_id, uname, msg = login_account(uid, pin)
        if not valid_id:
            gr.Warning(msg)
            return (
                None, None, gr.update(visible=True), gr.update(visible=False),
                "", gr.update(), gr.update(), gr.update()
            )
        gr.Info(msg)
        return enter_app(valid_id, uname)

    def handle_logout():
        return (
            None,
            None,
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            gr.update(choices=[], value=None),
            "### Select a friend to start messaging",
            render_chat_history(None, None),
        )

    def handle_add_friend(uid, target_id):
        status = add_friend_by_id(uid, target_id)
        if "Added" in status:
            gr.Info(status)
        else:
            gr.Warning(status)
        friends = get_friend_choices(uid)
        clean_target = target_id.strip().upper() if target_id else ""
        selected = next((f for f in friends if f"({clean_target})" in f), friends[0] if friends else None)
        header = f"### Chatting with {selected}" if selected else "### Select a friend to chat"
        return (
            "",
            gr.update(choices=friends, value=selected),
            header,
            render_chat_history(uid, selected),
        )

    def handle_select_friend(uid, selected_friend):
        header = f"### Chatting with {selected_friend}" if selected_friend else "### Select a friend to chat"
        return header, render_chat_history(uid, selected_friend)

    def handle_send(uid, selected_friend, text, media_file):
        try:
            err = send_direct_message(uid, selected_friend, text, media_file)
        except Exception as e:
            gr.Error(f"Failed to send media: {str(e)}")
            return gr.update(), gr.update(), gr.update()

        if err:
            gr.Warning(err)
            return gr.update(), gr.update(), gr.update()
        return "", None, render_chat_history(uid, selected_friend)

    def handle_refresh(uid, selected_friend):
        friends = get_friend_choices(uid)
        active = selected_friend if selected_friend in friends else (friends[0] if friends else None)
        header = f"### Chatting with {active}" if active else "### Select a friend to chat"
        return gr.update(choices=friends, value=active), header, render_chat_history(uid, active)

    reg_btn.click(
        fn=handle_register,
        inputs=[reg_name, reg_pin, reg_custom_id],
        outputs=[
            current_user_id, current_user_name, auth_section, chat_section,
            user_banner, friend_selector, chat_header, chat_display
        ],
    )

    login_btn.click(
        fn=handle_login,
        inputs=[login_id, login_pin],
        outputs=[
            current_user_id, current_user_name, auth_section, chat_section,
            user_banner, friend_selector, chat_header, chat_display
        ],
    )

    logout_btn.click(
        fn=handle_logout,
        outputs=[
            current_user_id, current_user_name, auth_section, chat_section,
            user_banner, friend_selector, chat_header, chat_display
        ],
    )

    add_friend_btn.click(
        fn=handle_add_friend,
        inputs=[current_user_id, friend_id_input],
        outputs=[friend_id_input, friend_selector, chat_header, chat_display],
    )

    friend_selector.change(
        fn=handle_select_friend,
        inputs=[current_user_id, friend_selector],
        outputs=[chat_header, chat_display],
    )

    send_btn.click(
        fn=handle_send,
        inputs=[current_user_id, friend_selector, msg_input, media_input],
        outputs=[msg_input, media_input, chat_display],
    )

    refresh_friends_btn.click(
        fn=handle_refresh,
        inputs=[current_user_id, friend_selector],
        outputs=[friend_selector, chat_header, chat_display],
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"),
        css=CUSTOM_CSS,
    )
