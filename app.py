import streamlit as st
import pandas as pd
from typing import List, Tuple
import time
from dataclasses import dataclass
from pathlib import Path
import difflib
import json
from pymongo import AsyncMongoClient
from datetime import datetime, timezone, timedelta
import pytz
from time_tracker import TimeTracker
import asyncio
import hashlib
import string

st.set_page_config(
    page_title="MT Post-Editing Tool",
    page_icon="🌍",
    layout="centered"
)

st.markdown("""
<style>
  div[data-testid="stSidebarHeader"] > img, div[data-testid="collapsedControl"] > img {
      height: 3rem;
      width: auto;
      align-self: center;
  }
  
  div[data-testid="stSidebarHeader"], div[data-testid="stSidebarHeader"] > *,
  div[data-testid="collapsedControl"], div[data-testid="collapsedControl"] > * {
      display: flex;
      align-items: center;
  }
</style>
            """, unsafe_allow_html=True)

st.logo("static/old_unior-nlp.jpg",
        link=None, icon_image="static/old_unior-nlp.jpg")

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
    """Calculate insertions and deletions between original and edited text, ignoring punctuation"""
    # Remove punctuation and split
    translator = str.maketrans('', '', string.punctuation)
    original_words = original.translate(translator).split()
    edited_words = edited.translate(translator).split()
    
    d = difflib.Differ()
    diff = list(d.compare(original_words, edited_words))

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
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False


async def load_css():
    """Load and apply custom CSS styles"""
    with open("static/styles.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def highlight_differences(original: str, edited: str) -> str:
    """Create HTML with highlighted differences, ignoring punctuation"""
    # Remove punctuation and split
    translator = str.maketrans('', '', string.punctuation)
    original_words = original.translate(translator).split()
    edited_words = edited.translate(translator).split()
    
    d = difflib.Differ()
    diff = list(d.compare(original_words, edited_words))

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

    if user_data:
        # Load time tracker if available
        if 'time_tracker' in user_data:
            st.session_state.time_tracker = TimeTracker.from_dict(
                user_data['time_tracker'])
        
        # Return metrics and full text if they exist
        metrics = user_data.get('metrics', [])
        full_text = user_data.get('full_text', [])
        
        if metrics and full_text:
            return pd.DataFrame(metrics), full_text
    
    return pd.DataFrame(), []


def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


async def create_user(name: str, surname: str, password: str) -> bool:
    """Create a new user in MongoDB"""
    db = await get_mongo_connection()
    users = db['users']
    
    # Check if user already exists
    existing_user = await users.find_one({
        'name': name,
        'surname': surname
    })
    
    if existing_user:
        return False
    
    # Create new user
    user_doc = {
        'name': name,
        'surname': surname,
        'password': hash_password(password),
        'created_at': datetime.now(timezone.utc)
    }
    
    await users.insert_one(user_doc)
    return True


async def verify_user(name: str, surname: str, password: str) -> bool:
    """Verify user credentials against MongoDB"""
    db = await get_mongo_connection()
    users = db['users']
    
    user = await users.find_one({
        'name': name,
        'surname': surname,
        'password': hash_password(password)
    })
    
    return user is not None


def main():
    asyncio.run(load_css())
    asyncio.run(init_session_state())

    # Hide sidebar if not authenticated
    if not st.session_state.authenticated:
        st.header("🌍 MT Post-Editing Tool")
        
        # Welcome message with improved styling
        st.markdown("""
            <div class="welcome-card">
                <p>Access your personalized post-editing workspace by logging in or creating a new account.</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Login/Register tabs with improved styling
        tabs = st.tabs(["🔑 Login", "✨ Register"])
        
        with tabs[0]:
            with st.form("login_form"):
                st.subheader("Welcome Back!")
                name = st.text_input("Name", key="login_name", placeholder="Enter your name")
                surname = st.text_input("Surname", key="login_surname", placeholder="Enter your surname")
                password = st.text_input("Password", type="password", key="login_password", 
                                      placeholder="Enter your password")
                
                submit_button = st.form_submit_button("Sign In", use_container_width=True)
                
                # Add this new block to handle login
                if submit_button:
                    if name and surname and password:
                        with st.spinner("Verifying credentials..."):
                            if asyncio.run(verify_user(name, surname, password)):
                                st.session_state.authenticated = True
                                st.session_state.user_name = name
                                st.session_state.user_surname = surname
                                st.success("Login successful!")
                                st.rerun()
                            else:
                                st.error("Invalid credentials. Please try again.")
                    else:
                        st.error("Please fill in all fields")

            st.markdown("""
                        </form>
                    </div>
                    <div class="info-sidebar">
                        <h4>Why Sign In?</h4>
                        <ul>
                            <li>Save your progress automatically</li>
                            <li>Resume your work anytime</li>
                            <li>Track your editing statistics</li>
                            <li>Access advanced features</li>
                        </ul>
                    </div>
                </div>
            """, unsafe_allow_html=True)
        
        with tabs[1]:
            with st.form("register_form"):
                st.subheader("Create Account")
                new_name = st.text_input("Name", key="reg_name", placeholder="Enter your name")
                new_surname = st.text_input("Surname", key="reg_surname", placeholder="Enter your surname")
                
                # Password fields in columns for better layout
                pass_col1, pass_col2 = st.columns(2)
                with pass_col1:
                    new_password = st.text_input("Password", type="password", 
                                               key="reg_password", 
                                               placeholder="Choose password")
                with pass_col2:
                    confirm_password = st.text_input("Confirm Password", 
                                                   type="password",
                                                   placeholder="Repeat password")
                
                # Password requirements hint
                st.caption("""
                    Password requirements:
                    - At least 8 characters
                    - Mix of letters and numbers
                    """)
                
                register_button = st.form_submit_button("Create Account", use_container_width=True)
                
                if register_button:
                    if new_name and new_surname and new_password:
                        if len(new_password) < 8:
                            st.error("Password must be at least 8 characters long")
                            return
                            
                        if new_password != confirm_password:
                            st.error("Passwords do not match")
                            return
                        
                        with st.spinner("Creating your account..."):
                            if asyncio.run(create_user(new_name, new_surname, new_password)):
                                st.success("✅ Registration successful!")
                                st.info("Please proceed to login with your credentials")
                                # Clear registration fields
                                st.session_state.pop('reg_name', None)
                                st.session_state.pop('reg_surname', None)
                                st.session_state.pop('reg_password', None)
                            else:
                                st.error("An account with these details already exists")
                    else:
                        st.error("Please fill in all fields")

            st.markdown("""
                <div class="info-sidebar">
                    <h4>Benefits of Registration</h4>
                    <ul>
                        <li>Free access to all features</li>
                        <li>Secure data storage</li>
                        <li>Progress tracking</li>
                        <li>Cloud backup of your work</li>
                    </ul>
                </div>
            """, unsafe_allow_html=True)
        
        # Footer with additional information
        st.markdown("""
            <div class="login-footer">
                <p>By using this tool, you agree to participate to our project.</p>
                <p>Need help? Contact <a href="mailto:antonio.castaldo@phd.unipi.it">antonio.castaldo@phd.unipi.it</a></p>
            </div>
            """, unsafe_allow_html=True)
        
        return

    # If authenticated, show sidebar and main content
    with st.sidebar:
        st.write("Welcome to the **MT Post-Editing Tool**.")
        st.markdown("## 🧑‍💻 Tool Settings")

        # Show user info and logout button
        st.write(f"Logged in as: **{st.session_state.user_name} {st.session_state.user_surname}**")
        if st.button("🚪 Logout", use_container_width=True):
            # Clear session state
            st.session_state.authenticated = False
            st.session_state.user_name = ""
            st.session_state.user_surname = ""
            st.rerun()

        # Settings section only shown when logged in
        st.divider()
        st.write("➦ **Tool Settings and Controls**")

        # Auto-save toggle
        st.session_state.auto_save = st.toggle(
            "Enable auto-save", value=st.session_state.auto_save)

        # Show last saved time if available
        if st.session_state.last_saved:
            local_tz = pytz.timezone('Europe/Rome')
            local_time = st.session_state.last_saved.astimezone(local_tz)
            st.caption(
                f"Last saved: {local_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Save/Load buttons
        if st.button("💾 Save",  use_container_width=True):
            with st.spinner("Saving progress..."):
                df = pd.DataFrame([vars(m) for m in st.session_state.edit_metrics])
                asyncio.run(save_to_mongodb(
                    st.session_state.user_name, 
                    st.session_state.user_surname, 
                    df))
                st.session_state.last_saved = datetime.now(timezone.utc)
                st.success("Progress saved!")

        if st.button("📂 Load Progress", use_container_width=True):
            with st.spinner("Loading previous work..."):
                existing_data, full_text = asyncio.run(
                    load_from_mongodb(st.session_state.user_name, 
                                    st.session_state.user_surname))
                
                if not existing_data.empty and full_text:
                    # Create edit metrics from loaded data
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
                    
                    # Set segments and current segment
                    st.session_state.segments = full_text
                    
                    # Find the last edited segment
                    if st.session_state.edit_metrics:
                        last_edited_segment = max(
                            m.segment_id for m in st.session_state.edit_metrics)
                        st.session_state.current_segment = last_edited_segment
                    else:
                        st.session_state.current_segment = 0
                        
                    st.success("Previous work loaded!")
                    st.rerun()
                else:
                    st.warning("No previous work found. Please upload new files to begin.")

    # Only show main content if authenticated
    if st.session_state.authenticated:
        # Instructions
        st.markdown("""
            <div class="card pt-serif">
                <p><strong>Hi, I'm Antonio. 👋</strong></p>
                <p>I'm a PhD candidate in Artificial Intelligence at the University of Pisa, working on Creative Machine Translation with LLMs.</p>
                <p>My goal is to develop translation systems that can preserve style, tone, and creative elements while accurately conveying meaning across languages.</p>
                <p>Learn more about me at <a href="https://www.ancastal.com" target="_blank">www.ancastal.com</a></p>
            </div>
        """, unsafe_allow_html=True)

        with st.expander("Instructions", expanded=False):
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

        # After the progress bar and before displaying segments, add context control
        with st.sidebar:
            st.divider()
            context_range = st.slider(
                "Context Size",
                min_value=2,
                max_value=10,
                value=5,
                help="Number of segments to show before and after the current segment"
            )

        # Display current segment with improved styling
        if st.session_state.segments:
            start_idx = max(0, st.session_state.current_segment - context_range)
            end_idx = min(len(st.session_state.segments), st.session_state.current_segment + context_range + 1)

            with st.container(border=True):
                # Show all context in a single expander
                with st.expander("📖 Full Context View", expanded=True):
                    # Previous context merged into one text area
                    if start_idx < st.session_state.current_segment:
                        previous_segments = []
                        for idx in range(start_idx, st.session_state.current_segment):
                            source, _ = st.session_state.segments[idx]
                            previous_segments.append(f"[{idx + 1}] {source}")
                        
                        if previous_segments:
                            st.markdown("**Previous segments:**")
                            st.info("\n\n".join(previous_segments))

                    
                    # Current segment (highlighted differently)
                    current_source, current_translation = st.session_state.segments[st.session_state.current_segment]
                    st.markdown(f"**Current Segment [{st.session_state.current_segment + 1}]:**")
                    st.warning(current_source)  # Using warning to highlight current segment
                    

                    # Following context merged into one text area
                    if end_idx > st.session_state.current_segment + 1:
                        following_segments = []
                        for idx in range(st.session_state.current_segment + 1, end_idx):
                            source, _ = st.session_state.segments[idx]
                            following_segments.append(f"[{idx + 1}] {source}")
                        
                        if following_segments:
                            st.markdown("**Following segments:**")
                            st.info("\n\n".join(following_segments))

                
                # Existing edit area code remains the same
                existing_edit = next(
                    (m for m in st.session_state.edit_metrics
                     if m.segment_id == st.session_state.current_segment),
                    None
                )

                most_recent_edit = None
                for metric in reversed(st.session_state.edit_metrics):
                    if metric.segment_id == st.session_state.current_segment:
                        most_recent_edit = metric
                        break

                initial_value = (most_recent_edit.edited if most_recent_edit
                                 else (existing_edit.edited if existing_edit
                                       else current_translation))

                if st.session_state.current_segment not in st.session_state.original_texts:
                    st.session_state.original_texts[st.session_state.current_segment] = initial_value

                if st.session_state.current_segment != st.session_state.active_segment:
                    if st.session_state.active_segment is not None:
                        st.session_state.time_tracker.pause_segment(st.session_state.active_segment)
                    st.session_state.time_tracker.start_segment(st.session_state.current_segment)
                    st.session_state.time_tracker.resume_segment(st.session_state.current_segment)
                    st.session_state.active_segment = st.session_state.current_segment

                edited_text = st.text_area(
                    "Translation:",
                    value=initial_value,
                    key=f"edit_area_{st.session_state.current_segment}",
                    on_change=lambda: st.session_state.time_tracker.update_activity(st.session_state.current_segment)
                )

        # Navigation buttons with emojis and improved layout
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Previous",
                         key="prev_segment",
                         disabled=st.session_state.current_segment == 0):
                save_metrics(current_source, current_translation, edited_text)
                st.session_state.time_tracker.pause_segment(
                    st.session_state.current_segment)
                st.session_state.current_segment -= 1
                st.session_state.active_segment = None  # Reset active segment
                st.rerun()

        with col2:
            # Check if we're on the last segment
            is_last_segment = st.session_state.current_segment == len(
                st.session_state.segments) - 1

            if is_last_segment:
                if st.button("🏁 Finish", key="finish_button", type="primary"):
                    save_metrics(current_source, current_translation, edited_text)
                    st.session_state.time_tracker.pause_segment(
                        st.session_state.current_segment)
                    st.session_state.current_segment += 1
                    st.session_state.active_segment = None  # Reset active segment
                    st.rerun()
            else:
                if st.button("Next ➡️", key="next_segment"):
                    # Update final stats for current segment
                    st.session_state.time_tracker.update_activity(st.session_state.current_segment)
                    # Save metrics and pause tracking
                    save_metrics(current_source, current_translation, edited_text)
                    st.session_state.time_tracker.pause_segment(st.session_state.current_segment)
                    # Move to next segment
                    st.session_state.current_segment += 1
                    st.session_state.active_segment = None  # Reset active segment
                    st.rerun()

        # Show editing statistics in expander
        if st.session_state.current_segment in st.session_state.time_tracker.sessions:
            st.divider()
            with st.expander("📊 Post-Editing Statistics", expanded=True):
                col1, col2, col3, col4 = st.columns(4)

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

                with col2:
                    if st.session_state.current_segment in st.session_state.time_tracker.sessions:
                        idle_time = st.session_state.time_tracker.sessions[st.session_state.current_segment].idle_time
                        idle_minutes = int(idle_time // 60)
                        idle_seconds = int(idle_time % 60)
                        st.metric(
                            "Idle Time",
                            f"{idle_minutes}m {idle_seconds}s",
                            help="Time spent idle (>30s without activity)"
                        )

                insertions, deletions = calculate_edit_distance(
                    current_translation, edited_text)
                with col3:
                    st.metric(
                        "Insertions",
                        f"{insertions}",
                        help="Number of inserted words"
                    )

                with col4:
                    st.metric(
                        "Deletions",
                        f"{deletions}",
                        help="Number of deleted words"
                    )

            with st.expander("👀 View Changes", expanded=True):
                st.markdown(highlight_differences(
                    current_translation, edited_text), unsafe_allow_html=True)

    else:
        # Show welcome message for non-authenticated users
        st.markdown("""
            <div class="card pt-serif">
                <p><strong>Welcome to the MT Post-Editing Tool! 👋</strong></p>
                <p>Please login using the button in the sidebar to get started.</p>
            </div>
        """, unsafe_allow_html=True)


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
                    <p><strong>Thanks for using my tool! </strong></p>
                    <p>Feel free to send me an email for any feedback or suggestions.</p>
                </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
