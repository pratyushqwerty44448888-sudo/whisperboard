import os
import html
from datetime import datetime
import psycopg2
import cloudinary
import cloudinary.uploader
import gradio as gr

# --- Configuration ---
DATABASE_URL = os.environ.get("DATABASE_URL")

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)


# --- Database & Media Functions ---
def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            alias TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS image_url TEXT;")
    conn.commit()
    cursor.close()
    conn.close()


def upload_media(file_path):
    if not file_path:
        return None
    result = cloudinary.uploader.upload(file_path, resource_type="auto")
    return result.get("secure_url")


def add_post(alias, category, content, file_path):
    has_text = bool(content and content.strip())
    has_media = bool(file_path)

    if not has_text and not has_media:
        return

    clean_alias = alias.strip() if alias and alias.strip() else "Anonymous"
    clean_content = content.strip() if has_text else ""
    timestamp = datetime.now().strftime("%b %d, %Y • %I:%M %p")
    image_url = upload_media(file_path) if has_media else None

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO posts (alias, category, content, image_url, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (clean_alias, category, clean_content, image_url, timestamp),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_posts(category_filter="All"):
    conn = get_connection()
    cursor = conn.cursor()
    if category_filter == "All":
        cursor.execute(
            "SELECT alias, category, content, image_url, created_at FROM posts ORDER BY id DESC"
        )
    else:
        cursor.execute(
            """
            SELECT alias, category, content, image_url, created_at
            FROM posts WHERE category = %s ORDER BY id DESC
            """,
            (category_filter,),
        )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# --- UI Rendering ---
def render_feed(category_filter="All"):
    posts = get_posts(category_filter)
    if not posts:
        return """
        <div class="empty-state">
            <p>No posts here yet. Click <b>+ New Post</b> to share a thought, image, or GIF!</p>
        </div>
        """

    cards_html = []
    for alias, category, content, image_url, created_at in posts:
        safe_alias = html.escape(alias)
        safe_category = html.escape(category)
        safe_content = html.escape(content).replace("\n", "<br>") if content else ""

        text_block = f'<div class="post-body">{safe_content}</div>' if safe_content else ""
        media_block = ""
        if image_url:
            safe_url = html.escape(image_url)
            media_block = f"""
            <div class="post-media">
                <img src="{safe_url}" alt="User uploaded media" loading="lazy" />
            </div>
            """

        card = f"""
        <div class="post-card">
            <div class="post-header">
                <div class="author-info">
                    <span class="avatar">👻</span>
                    <span class="alias">{safe_alias}</span>
                    <span class="badge">{safe_category}</span>
                </div>
                <span class="timestamp">{created_at}</span>
            </div>
            {text_block}
            {media_block}
        </div>
        """
        cards_html.append(card)

    return "".join(cards_html)


# --- Custom Styling ---
CUSTOM_CSS = """
.gradio-container {
    max-width: 780px !important;
    margin: 0 auto !important;
    padding-top: 24px !important;
}
.composer-box {
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;
}
.post-card {
    background: var(--background-fill-primary);
    border: 1px solid var(--border-color-primary);
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 14px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}
.post-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    flex-wrap: wrap;
    gap: 8px;
}
.author-info {
    display: flex;
    align-items: center;
    gap: 8px;
}
.alias {
    font-weight: 600;
    font-size: 0.95rem;
}
.badge {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 999px;
    background: var(--color-accent-soft);
    color: var(--color-accent);
}
.timestamp {
    font-size: 0.8rem;
    color: var(--body-text-color-subdued);
}
.post-body {
    font-size: 1rem;
    line-height: 1.55;
    word-wrap: break-word;
    margin-bottom: 10px;
}
.post-media {
    margin-top: 8px;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border-color-primary);
    background: var(--background-fill-secondary);
    display: flex;
    justify-content: center;
}
.post-media img {
    max-width: 100%;
    max-height: 480px;
    object-fit: contain;
    display: block;
}
.empty-state {
    text-align: center;
    padding: 40px 20px;
    border: 1px dashed var(--border-color-primary);
    border-radius: 12px;
    color: var(--body-text-color-subdued);
}
"""

init_db()

with gr.Blocks(
    theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"),
    css=CUSTOM_CSS,
    title="WhisperBoard",
) as demo:
    composer_open = gr.State(False)

    with gr.Row(equal_height=True):
        with gr.Column(scale=3):
            gr.Markdown(
                "# 👻 WhisperBoard\n*Share thoughts, images, and GIFs anonymously.*"
            )
        with gr.Column(scale=1, min_width=140):
            new_post_btn = gr.Button("➕ New Post", variant="primary", size="lg")

    with gr.Group(visible=False, elem_classes="composer-box") as composer_group:
        gr.Markdown("### Create an Anonymous Post")
        with gr.Row():
            alias_input = gr.Textbox(
                label="Display Alias (Optional)",
                placeholder="Leave blank to post as 'Anonymous'",
                scale=2,
            )
            category_input = gr.Dropdown(
                label="Topic",
                choices=["General", "Confession", "Advice", "Tech & Code", "Memes & GIFs", "Random"],
                value="General",
                scale=1,
            )
        content_input = gr.Textbox(
            label="Your Message (Optional if attaching an image/GIF)",
            placeholder="Write what's on your mind...",
            lines=3,
            max_lines=10,
        )
        media_input = gr.File(
            label="Attach Image or GIF (PNG, JPG, WEBP, GIF)",
            file_types=[".png", ".jpg", ".jpeg", ".webp", ".gif"],
            type="filepath",
        )
        with gr.Row():
            cancel_btn = gr.Button("Cancel", variant="secondary")
            submit_btn = gr.Button("Publish Post", variant="primary")

    with gr.Row(equal_height=True):
        filter_dropdown = gr.Dropdown(
            choices=["All", "General", "Confession", "Advice", "Tech & Code", "Memes & GIFs", "Random"],
            value="All",
            label="Filter Feed by Topic",
            scale=4,
        )
        refresh_btn = gr.Button("🔄 Refresh", scale=1, min_width=110)

    feed_html = gr.HTML(value=render_feed())

    def toggle_composer(is_open):
        new_state = not is_open
        btn_label = "✖ Close" if new_state else "➕ New Post"
        return new_state, gr.update(visible=new_state), gr.update(value=btn_label)

    def handle_submit(alias, category, content, file_path, current_filter):
        has_text = bool(content and content.strip())
        has_media = bool(file_path)

        if not has_text and not has_media:
            gr.Warning("Please write a message or attach an image/GIF before publishing.")
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                True,
                gr.update(visible=True),
                gr.update(value="✖ Close"),
                gr.update(),
            )

        try:
            add_post(alias, category, content, file_path)
            gr.Info("Your post is live!")
        except Exception as e:
            gr.Error(f"Upload failed: {str(e)}")
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                True,
                gr.update(visible=True),
                gr.update(value="✖ Close"),
                gr.update(),
            )

        return (
            "",
            "",
            None,
            False,
            gr.update(visible=False),
            gr.update(value="➕ New Post"),
            render_feed(current_filter),
        )

    def handle_cancel():
        return False, gr.update(visible=False), gr.update(value="➕ New Post")

    new_post_btn.click(
        fn=toggle_composer,
        inputs=[composer_open],
        outputs=[composer_open, composer_group, new_post_btn],
    )
    cancel_btn.click(
        fn=handle_cancel,
        outputs=[composer_open, composer_group, new_post_btn],
    )
    submit_btn.click(
        fn=handle_submit,
        inputs=[alias_input, category_input, content_input, media_input, filter_dropdown],
        outputs=[
            alias_input,
            content_input,
            media_input,
            composer_open,
            composer_group,
            new_post_btn,
            feed_html,
        ],
    )
    filter_dropdown.change(fn=render_feed, inputs=[filter_dropdown], outputs=[feed_html])
    refresh_btn.click(fn=render_feed, inputs=[filter_dropdown], outputs=[feed_html])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
