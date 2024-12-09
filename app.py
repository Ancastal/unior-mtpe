import streamlit as st
import pandas as pd
from typing import List, Tuple
import time
from dataclasses import dataclass
from pathlib import Path
import difflib
import json
from pymongo import AsyncMongoClient
from datetime import datetime, timezone
import pytz
from time_tracker import TimeTracker
import asyncio

st.set_page_config(
    page_title="MT Post-Editing Tool",
    page_icon="🌍",
    layout="centered"
)

st.logo("static/unior-nlp.jpg", size="large",
        link=None, icon_image="static/unior-nlp.jpg")

#  hide_st_style = """
#     <style>
#     #MainMenu {visibility: hidden;}
#     header {visibility: hidden;}
#     footer {visibility: hidden;}
#     </style>
#  """
#
# st.markdown(hide_st_style, unsafe_allow_html=True)


@dataclass
class EditMetrics:
    """Class to store metrics for each segment edit"""
    segment_id: int
    source: str
    original: str
    edited: str
    edit_time: float
    insertions: int
    deletions: int


def calculate_edit_distance(original: str, edited: str) -> Tuple[int, int]:
    """Calculate insertions and deletions between original and edited text"""
    d = difflib.Differ()
    diff = list(d.compare(original.split(), edited.split()))

    insertions = len([d for d in diff if d.startswith('+')])
    deletions = len([d for d in diff if d.startswith('-')])

    return insertions, deletions


def load_segments(source_file, translation_file) -> List[Tuple[str, str]]:
    """Load segments from uploaded files"""
    if source_file is None or translation_file is None:
        return []

    source_content = source_file.getvalue().decode("utf-8")
    translation_content = translation_file.getvalue().decode("utf-8")

    source_lines = [line.strip()
                    for line in source_content.split('\n') if line.strip()]
    translation_lines = [line.strip()
                         for line in translation_content.split('\n') if line.strip()]

    # Ensure both files have same number of lines
    if len(source_lines) != len(translation_lines):
        raise ValueError(
            "Source and translation files must have the same number of lines")

    return list(zip(source_lines, translation_lines))


async def init_session_state():
    """Initialize session state variables"""
    if 'current_segment' not in st.session_state:
        st.session_state.current_segment = 0
    if 'segments' not in st.session_state:
        st.session_state.segments = []
    if 'edit_metrics' not in st.session_state:
        st.session_state.edit_metrics = []
    if 'segment_start_times' not in st.session_state:
        st.session_state.segment_start_times = {}
    if 'original_texts' not in st.session_state:
        st.session_state.original_texts = {}
    if 'user_name' not in st.session_state:
        st.session_state.user_name = ""
    if 'user_surname' not in st.session_state:
        st.session_state.user_surname = ""
    if 'time_tracker' not in st.session_state:
        st.session_state.time_tracker = TimeTracker()
    if 'active_segment' not in st.session_state:
        st.session_state.active_segment = None
    if 'last_saved' not in st.session_state:
        st.session_state.last_saved = None
    if 'auto_save' not in st.session_state:
        st.session_state.auto_save = True


async def load_css():
    """Load and apply custom CSS styles"""
    with open("static/styles.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def highlight_differences(original: str, edited: str) -> str:
    """Create HTML with highlighted differences"""
    d = difflib.Differ()
    diff = list(d.compare(original.split(), edited.split()))

    html_parts = []
    for word in diff:
        if word.startswith('  '):
            html_parts.append(f'<span>{word[2:]}</span>')
        elif word.startswith('- '):
            html_parts.append(
                f'<span style="background-color: #ffcdd2">{word[2:]}</span>')
        elif word.startswith('+ '):
            html_parts.append(
                f'<span style="background-color: #c8e6c9">{word[2:]}</span>')

    return ' '.join(html_parts)


async def get_mongo_connection():
    """Get MongoDB connection"""
    connection_string = st.secrets["MONGO_CONNECTION_STRING"]
    client = AsyncMongoClient(connection_string,
                              tlsAllowInvalidCertificates=True)  # For development only
    db = client['mtpe_database']
    return db


async def save_to_mongodb(user_name: str, user_surname: str, metrics_df: pd.DataFrame):
    """Save metrics and full text to MongoDB"""
    db = await get_mongo_connection()
    collection = db['user_progress']

    # Convert DataFrame to dict and add user info
    progress_data = {
        'user_name': user_name,
        'user_surname': user_surname,
        'last_updated': datetime.now(),
        'metrics': metrics_df.to_dict('records'),
        'full_text': st.session_state.segments,
        'time_tracker': st.session_state.time_tracker.to_dict()
    }

    # Update or insert document
    await collection.update_one(
        {'user_name': user_name, 'user_surname': user_surname},
        {'$set': progress_data},
        upsert=True
    )


async def load_from_mongodb(user_name: str, user_surname: str) -> Tuple[pd.DataFrame, List[str]]:
    """Load metrics and full text from MongoDB"""
    db = await get_mongo_connection()
    collection = db['user_progress']

    # Find user's progress
    user_data = await collection.find_one({
        'user_name': user_name,
        'user_surname': user_surname
    })

    if user_data and 'metrics' in user_data:
        # Load time tracker if available
        if 'time_tracker' in user_data:
            st.session_state.time_tracker = TimeTracker.from_dict(
                user_data['time_tracker'])
        return pd.DataFrame(user_data['metrics']), user_data.get('full_text', [])
    return pd.DataFrame(), []


def main():
    asyncio.run(load_css())
    st.header("🌍 MT Post-Editing Tool")
    asyncio.run(init_session_state())

    # Sidebar for user information
    with st.sidebar:
        st.write("Welcome to the **MT Post-Editing Tool**.")
        st.markdown("## 🧑‍💻 Tool Settings")
        st.text(
            "➦ Follow the instructions to get started.\n➦ Enter name and surname below.")

        # User Profile section
        with st.container(border=True):
            user_name = st.text_input(
                "**Name**", value=st.session_state.get('user_name', ''))
            user_surname = st.text_input(
                "**Surname**", value=st.session_state.get('user_surname', ''))

            if user_name and user_surname:
                st.session_state.user_name = user_name
                st.session_state.user_surname = user_surname

                # Add auto-save toggle
                st.session_state.auto_save = st.toggle(
                    "Enable auto-save", value=st.session_state.auto_save)

                # Show last saved time if available
                if st.session_state.last_saved:
                    # Adjust timezone as needed
                    local_tz = pytz.timezone('Europe/Rome')
                    local_time = st.session_state.last_saved.astimezone(
                        local_tz)
                    st.caption(
                        f"Last saved: {local_time.strftime('%Y-%m-%d %H:%M:%S')}")

                if st.button("💾 Save Progress", use_container_width=True):
                    with st.spinner("Saving progress..."):
                        df = pd.DataFrame(
                            [vars(m) for m in st.session_state.edit_metrics])
                        asyncio.run(save_to_mongodb(
                            user_name, user_surname, df))
                        st.session_state.last_saved = datetime.now(
                            timezone.utc)
                        st.success("Progress saved!")

                if st.button("📂 Load Progress", use_container_width=True):
                    with st.spinner("Loading previous work..."):
                        existing_data, full_text = asyncio.run(
                            load_from_mongodb(user_name, user_surname))

                        if not existing_data.empty and full_text:
                            st.session_state.edit_metrics = [
                                EditMetrics(
                                    segment_id=row['segment_id'],
                                    source=row['source'],
                                    original=row['original'],
                                    edited=row['edited'],
                                    edit_time=row['edit_time'],
                                    insertions=row['insertions'],
                                    deletions=row['deletions']
                                )
                                for _, row in existing_data.iterrows()
                            ]

                            st.session_state.segments = full_text
                            last_edited_segment = max(
                                row['segment_id'] for _, row in existing_data.iterrows())
                            st.session_state.current_segment = last_edited_segment
                            st.success("Previous work loaded!")
                            st.rerun()
                        else:
                            st.info("No previous work found")
            else:
                st.error("Enter your name and surname.")

        # Footer
    st.sidebar.markdown("""
        <div style='position: fixed; bottom: 0; width: 100%; text-align: center; padding: 10px; background: white;'>
            <small style='color: #666;'>
                Made with ❤️ by <a href="https://www.ancastal.com" target="_blank">Antonio Castaldo</a>
            </small>
        </div>
    """, unsafe_allow_html=True)

    # Instructions

    # Render header outside tabs
    st.markdown("""
        <div class="card pt-serif">
            <p><strong>Hi, I'm Antonio. 👋</strong></p>
            <p>I'm a PhD candidate in Artificial Intelligence at the University of Pisa, working on Creative Machine Translation with LLMs.</p>
            <p>My goal is to develop translation systems that can preserve style, tone, and creative elements while accurately conveying meaning across languages.</p>
            <p>Learn more about me at <a href="https://www.ancastal.com" target="_blank">www.ancastal.com</a></p>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("📖 Instructions", expanded=False):
        st.markdown("##### Getting Started")
        st.markdown("""
        1. Enter your name and surname in the sidebar to enable progress tracking
        2. Upload a text file containing one translation per line
        3. Edit each segment to improve the translation quality
        """)

        st.markdown("##### Navigation")
        st.markdown("""
        - Use the segment selector dropdown to jump to any segment
        - Use the Previous/Next buttons to move between segments
        - The progress bar shows your overall completion status
        """)

        st.markdown("##### Features")
        st.markdown("""
        - 🔄 **Auto-save:** Your progress is automatically saved as you edit (when enabled)
        - 📊 **Real-time metrics:** Track editing time, insertions, and deletions
        - 👀 **Visual diff:** See your changes highlighted in real-time
        - 💾 **Progress tracking:** Resume your work at any time
        """)

    st.markdown("""
                <div class="info-card">
                    <p class="pt-serif text-sm"><strong>Thanks for using my tool! 😊</strong></p>
                    <p class="text-center text-muted">Feel free to send me an email for any feedback or suggestions.</p>
                </div>
                """, unsafe_allow_html=True)

    asyncio.run(init_session_state())

    # File upload with styled container
    with st.container():
        source_file = st.file_uploader(
            "Upload source text file (one sentence per line)",
            type=['txt'],
            key="source_upload"
        )
        translation_file = st.file_uploader(
            "Upload translation file (one sentence per line)",
            type=['txt'],
            key="translation_upload"
        )

    if source_file and translation_file and len(st.session_state.segments) == 0:
        try:
            st.session_state.segments = load_segments(
                source_file, translation_file)
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    if not st.session_state.segments:
        return

    # Check if we've completed all segments
    if st.session_state.current_segment >= len(st.session_state.segments):
        st.divider()
        display_results()

    st.divider()

    # Add segment selection dropdown
    segment_idx = st.selectbox(
        "Select segment to edit",
        range(len(st.session_state.segments)),
        index=st.session_state.current_segment,
        format_func=lambda x: f"Segment {x + 1}",
        key='segment_select'
    )
    st.session_state.current_segment = segment_idx

    # Display progress
    st.progress(st.session_state.current_segment /
                len(st.session_state.segments))

    # Display current segment with improved styling
    if st.session_state.segments:
        current_source, current_translation = st.session_state.segments[
            st.session_state.current_segment]

        with st.container(border=True):
            # Source text with info styling
            st.markdown("**Source Text:**")
            st.info(current_source)

            # Check if this segment has already been edited
            existing_edit = next(
                (m for m in st.session_state.edit_metrics
                 if m.segment_id == st.session_state.current_segment),
                None
            )

            # Find the most recent edit for this segment
            most_recent_edit = None
            for metric in reversed(st.session_state.edit_metrics):
                if metric.segment_id == st.session_state.current_segment:
                    most_recent_edit = metric
                    break

            # Use the most recent edit if available, otherwise use existing_edit or current_translation
            initial_value = (most_recent_edit.edited if most_recent_edit
                             else (existing_edit.edited if existing_edit
                                   else current_translation))

            # Store original text for comparison
            if st.session_state.current_segment not in st.session_state.original_texts:
                st.session_state.original_texts[st.session_state.current_segment] = initial_value

            if st.session_state.current_segment != st.session_state.active_segment:
                # Pause previous segment if exists
                if st.session_state.active_segment is not None:
                    st.session_state.time_tracker.pause_segment(
                        st.session_state.active_segment)
                # Start or resume new segment
                st.session_state.time_tracker.start_segment(
                    st.session_state.current_segment)
                st.session_state.time_tracker.resume_segment(
                    st.session_state.current_segment)
                st.session_state.active_segment = st.session_state.current_segment

            edited_text = st.text_area(
                "Edit Translation:",
                value=initial_value,
                key=f"edit_area_{st.session_state.current_segment}"
            )

            # Start timing when text changes
            if edited_text != st.session_state.original_texts[st.session_state.current_segment]:
                if st.session_state.current_segment not in st.session_state.time_tracker.sessions:
                    st.session_state.time_tracker.start_segment(
                        st.session_state.current_segment)

    # Navigation buttons with emojis and improved layout
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ Previous",
                     key="prev_segment",
                     disabled=st.session_state.current_segment == 0):
            save_metrics(current_source, current_translation, edited_text)
            st.session_state.time_tracker.pause_segment(
                st.session_state.current_segment)
            st.session_state.current_segment -= 1
            st.rerun()

    with col2:
        # Check if we're on the last segment
        is_last_segment = st.session_state.current_segment == len(
            st.session_state.segments) - 1

        if is_last_segment:
            if st.button("🎉 Finish", key="finish_button", type="primary"):
                save_metrics(current_source, current_translation, edited_text)
                st.session_state.time_tracker.pause_segment(
                    st.session_state.current_segment)
                st.session_state.current_segment += 1
                st.rerun()
        else:
            if st.button("Next ➡️", key="next_segment"):
                save_metrics(current_source, current_translation, edited_text)
                st.session_state.time_tracker.pause_segment(
                    st.session_state.current_segment)
                st.session_state.current_segment += 1
                st.rerun()

    # Show editing statistics in expander
    if st.session_state.current_segment in st.session_state.time_tracker.sessions:
        st.divider()
        with st.expander("📊 Post-Editing Statistics", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                edit_time = st.session_state.time_tracker.get_editing_time(
                    st.session_state.current_segment)
                minutes = int(edit_time // 60)
                seconds = int(edit_time % 60)
                st.metric(
                    "Editing Time",
                    f"{minutes}m {seconds}s",
                    help="Time spent editing this segment"
                )

            insertions, deletions = calculate_edit_distance(
                current_translation, edited_text)
            with col2:
                st.metric(
                    "Insertions",
                    f"{insertions}",
                    help="Number of inserted words"
                )

            with col3:
                st.metric(
                    "Deletions",
                    f"{deletions}",
                    help="Number of deleted words"
                )

        with st.expander("👀 View Changes", expanded=True):
            st.markdown(highlight_differences(
                current_translation, edited_text), unsafe_allow_html=True)


def save_metrics(source: str, original: str, edited: str):
    """Save metrics for the current segment"""
    if edited == st.session_state.original_texts.get(st.session_state.current_segment, original):
        return

    edit_time = st.session_state.time_tracker.get_editing_time(
        st.session_state.current_segment)
    insertions, deletions = calculate_edit_distance(original, edited)

    metrics = EditMetrics(
        segment_id=st.session_state.current_segment,
        source=source,
        original=original,
        edited=edited,
        edit_time=edit_time,
        insertions=insertions,
        deletions=deletions
    )

    st.session_state.edit_metrics = [m for m in st.session_state.edit_metrics
                                     if m.segment_id != st.session_state.current_segment]
    st.session_state.edit_metrics.append(metrics)

    # Auto-save if enabled and user info is available
    if (st.session_state.get('auto_save', False) and
        st.session_state.get('user_name') and
            st.session_state.get('user_surname')):
        df = pd.DataFrame([vars(m) for m in st.session_state.edit_metrics])
        asyncio.run(save_to_mongodb(st.session_state.user_name,
                    st.session_state.user_surname, df))
        st.session_state.last_saved = datetime.now(timezone.utc)


def display_results():
    """Display final results and statistics"""
    # Convert metrics to DataFrame for easy analysis
    df = pd.DataFrame([vars(m) for m in st.session_state.edit_metrics])

    # Display statistics in a metrics container
    st.markdown("### Editing Statistics", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Segments", len(df))
    with col2:
        st.metric("Total Time", f"{df['edit_time'].sum():.1f}s")
    with col3:
        st.metric("Avg. Time/Segment", f"{df['edit_time'].mean():.1f}s")

    col4, col5, col6 = st.columns(3)
    with col4:
        st.metric("Total Insertions", int(df['insertions'].sum()))
    with col5:
        st.metric("Total Deletions", int(df['deletions'].sum()))
    with col6:
        st.metric("Total Edits", int(
            df['insertions'].sum() + df['deletions'].sum()))

    # Display detailed metrics
    st.divider()
    st.markdown("### Detailed Metrics", unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)

    # Download buttons
    st.divider()
    st.markdown("### Download Results", unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Download metrics as CSV",
            data=csv,
            file_name="post_editing_metrics.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col2:
        # Prepare JSON data
        json_data = []
        for metric in st.session_state.edit_metrics:
            json_data.append({
                "segment_id": metric.segment_id,
                "source": metric.source,
                "original_translation": metric.original,
                "post_edited": metric.edited,
                "edit_time_seconds": round(metric.edit_time, 2),
                "insertions": metric.insertions,
                "deletions": metric.deletions
            })

        json_str = json.dumps(json_data, indent=2, ensure_ascii=False)
        st.download_button(
            label="📥 Download segments as JSON",
            data=json_str,
            file_name="post_edited_segments.json",
            mime="application/json",
            use_container_width=True
        )

    st.divider()
    st.markdown("""
                <div class="info-card">
                    <p><strong>Thanks for using my tool! 😊</strong></p>
                    <p>Feel free to send me an email for any feedback or suggestions.</p>
                </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
