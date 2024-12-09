import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Optional
import pytz
import hashlib
import secrets
from enum import Enum


class UserRole(Enum):
    ADMIN = "admin"
    USER = "user"


# Page config
st.set_page_config(
    page_title="MTPE Manager Dashboard",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa;
        padding: 1rem;
        border-right: 1px solid #e9ecef;
    }
    .stApp {
        background-color: #ffffff;
    }
    .stMetric {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .user-card {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin: 10px 0;
    }
    .stats-card {
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin: 10px 0;
    }
    .plotly-chart {
        background-color: white;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .settings-item {
        margin: 1rem 0;
    }
    .settings-item label {
        font-size: 0.9rem;
        color: #666;
        margin-bottom: 0.4rem;
    }
    .version-info {
        font-size: 0.8rem;
        color: #888;
        margin-top: 1rem;
        opacity: 0.8;
    }
</style>
""", unsafe_allow_html=True)


def connect_to_mongodb():
    """Connect to MongoDB database"""
    connection_string = st.secrets["MONGO_CONNECTION_STRING"]
    client = MongoClient(
        connection_string,
        tlsAllowInvalidCertificates=True  # For development only
    )
    return client['mtpe_database']


def get_all_users() -> List[Dict]:
    """Get all users and their progress from MongoDB"""
    db = connect_to_mongodb()
    collection = db['user_progress']
    return list(collection.find())


def format_time(seconds: float) -> str:
    """Format seconds into a readable time string"""
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes}m {remaining_seconds}s"


def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def generate_salt() -> str:
    """Generate a random salt for password hashing"""
    return secrets.token_hex(16)


def authenticate_user(email: str, password: str) -> Optional[Dict]:
    """Authenticate a user and return user data if successful"""
    db = connect_to_mongodb()
    users = db['users']

    user = users.find_one({"email": email, "active": True})
    if not user:
        return None

    hashed_password = hash_password(password + user['salt'])
    if hashed_password != user['password_hash']:
        return None

    return user


def init_admin_if_needed():
    """Initialize admin user if no users exist"""
    db = connect_to_mongodb()
    users = db['users']

    if users.count_documents({}) == 0:
        create_user(
            email=st.secrets["ADMIN_EMAIL"],
            password=st.secrets["ADMIN_PASSWORD"],
            name="Admin",
            surname="User",
            role=UserRole.ADMIN
        )


def login_required(func):
    """Decorator to require login for certain pages/functions"""
    def wrapper(*args, **kwargs):
        if "user" not in st.session_state:
            st.warning("Please log in to access this page.")
            show_login_page()
            return
        return func(*args, **kwargs)
    return wrapper


def show_login_page():
    """Display login form"""
    st.title("Login")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            user = authenticate_user(email, password)
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("Invalid email or password")


def calculate_pe_effort(metrics: List[dict]) -> dict:
    """Calculate post-editing effort metrics"""
    if not metrics:
        return {
            'hter': 0,
            'avg_edit_distance': 0,
            'avg_time_per_word': 0,
            'throughput': 0
        }

    total_edits = sum(m.get('insertions', 0) + m.get('deletions', 0)
                      for m in metrics)
    total_words = sum(len(m.get('original', '').split()) for m in metrics)
    total_time = sum(m.get('edit_time', 0) for m in metrics)

    # HTER (Human-targeted Translation Edit Rate)
    hter = total_edits / total_words if total_words > 0 else 0

    # Average edit distance per segment
    avg_edit_distance = total_edits / len(metrics)

    # Average time per word (in seconds)
    avg_time_per_word = total_time / total_words if total_words > 0 else 0

    # Throughput (words per hour)
    hours = total_time / 3600  # convert seconds to hours
    throughput = total_words / hours if hours > 0 else 0

    return {
        'hter': hter,
        'avg_edit_distance': avg_edit_distance,
        'avg_time_per_word': avg_time_per_word,
        'throughput': throughput
    }


def calculate_temporal_effort(metrics: List[dict]) -> dict:
    """Calculate temporal effort metrics"""
    if not metrics:
        return {
            'avg_pause_ratio': 0,
            'avg_time_per_segment': 0,
            'processing_speed': 0
        }

    total_time = sum(m.get('edit_time', 0) for m in metrics)
    total_chars = sum(len(m.get('original', '')) for m in metrics)

    # Average time per segment
    avg_time_per_segment = total_time / len(metrics)

    # Processing speed (characters per second)
    processing_speed = total_chars / total_time if total_time > 0 else 0

    return {
        'avg_time_per_segment': avg_time_per_segment,
        'processing_speed': processing_speed
    }


def main():
    init_admin_if_needed()

    if "user" not in st.session_state:
        show_login_page()
        return

    # Original dashboard code
    st.title("👨‍💼 MTPE Manager Dashboard")
    st.markdown("""
    Welcome to the MTPE Manager Dashboard! Here you can monitor user progress, analyze performance metrics,
    and manage the post-editing project effectively.
    """)

    # Get all users data
    users_data = get_all_users()

    if not users_data:
        st.warning(
            "No user data available yet. Users need to complete some translations first.")
        return

    # Overview metrics
    st.header("📊 Project Overview")

    # Academic metrics section
    st.subheader("Post-editing Effort Analysis")

    # Calculate project-wide metrics
    all_metrics = [m for user in users_data for m in user.get('metrics', [])]
    pe_effort = calculate_pe_effort(all_metrics)
    temporal_effort = calculate_temporal_effort(all_metrics)

    # Display academic metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "HTER Score",
            f"{pe_effort['hter']:.3f}",
            help="Human-targeted Translation Edit Rate (lower is better)"
        )

    with col2:
        st.metric(
            "Words/Hour",
            f"{pe_effort['throughput']:.1f}",
            help="Post-editing throughput"
        )

    with col3:
        st.metric(
            "Avg Time/Word (s)",
            f"{pe_effort['avg_time_per_word']:.2f}",
            help="Average time spent per word"
        )

    with col4:
        st.metric(
            "Processing Speed",
            f"{temporal_effort['processing_speed']:.2f}",
            help="Characters processed per second"
        )

    # Add visualization for effort distribution
    st.subheader("Effort Distribution Analysis")

    col1, col2 = st.columns(2)

    with col1:
        # Edit distance distribution
        edit_distances = [m.get('insertions', 0) + m.get('deletions', 0)
                          for m in all_metrics]
        fig = px.histogram(
            edit_distances,
            title='Distribution of Edit Distances',
            labels={'value': 'Edit Distance', 'count': 'Frequency'},
            color_discrete_sequence=['#2E86C1']
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Time per word distribution
        times_per_word = [m.get('edit_time', 0) / len(m.get('original', '').split())
                          for m in all_metrics if len(m.get('original', '').split()) > 0]
        fig = px.histogram(
            times_per_word,
            title='Distribution of Time per Word',
            labels={'value': 'Seconds per Word', 'count': 'Frequency'},
            color_discrete_sequence=['#2E86C1']
        )
        st.plotly_chart(fig, use_container_width=True)

    # Create tabs for project overview and individual analysis
    tabs = st.tabs(["📈 Project Statistics", "👤 Individual Analysis"])

    # Project Statistics Tab
    with tabs[0]:
        st.header("👥 Project-wide Analysis")

        # Create subtabs for project analysis
        project_tabs = st.tabs([
            "📊 Overview",
            "⏱️ Temporal Analysis",
            "📝 Edit Patterns",
            "📈 Raw Data"
        ])

        # Overview Tab
        with project_tabs[0]:
            st.subheader("User Performance Analysis")

            # Prepare data for visualization
            user_stats = []
            for user in users_data:
                metrics = user.get('metrics', [])
                if not metrics:
                    continue

                total_segments = len(metrics)
                total_time = sum(m.get('edit_time', 0) for m in metrics)
                avg_time = total_time / total_segments
                total_edits = sum(m.get('insertions', 0) +
                                  m.get('deletions', 0) for m in metrics)

                user_stats.append({
                    'name': f"{user['user_name']} {user['user_surname']}",
                    'segments': total_segments,
                    'total_time': total_time,
                    'avg_time': avg_time,
                    'total_edits': total_edits
                })

            if user_stats:
                df = pd.DataFrame(user_stats)

                # User comparison charts
                col1, col2 = st.columns(2)

                with col1:
                    fig = px.bar(
                        df,
                        x='name',
                        y='segments',
                        title='Segments Completed by User',
                        color='segments',
                        color_continuous_scale='Viridis'
                    )
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    fig = px.bar(
                        df,
                        x='name',
                        y='avg_time',
                        title='Average Time per Segment (seconds)',
                        color='avg_time',
                        color_continuous_scale='Viridis'
                    )
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)

        # Temporal Analysis Tab
        with project_tabs[1]:
            st.subheader("Project Time Analysis")

            # Create DataFrame with all metrics
            all_metrics_df = pd.DataFrame([
                metric for user in users_data
                for metric in user.get('metrics', [])
            ])

            if not all_metrics_df.empty:
                # Time series of overall editing speed
                all_metrics_df['processing_speed'] = all_metrics_df.apply(
                    lambda x: len(x['original']) /
                    x['edit_time'] if x['edit_time'] > 0 else 0,
                    axis=1
                )

                # Average speed over time
                fig = px.line(
                    all_metrics_df,
                    x=all_metrics_df.index,
                    y='processing_speed',
                    title='Project-wide Editing Speed Trend',
                    labels={'index': 'Segment Number',
                            'processing_speed': 'Characters/Second'}
                )
                st.plotly_chart(fig, use_container_width=True)

                # Time distribution analysis
                col1, col2 = st.columns(2)

                with col1:
                    # Time per word distribution
                    times_per_word = all_metrics_df['edit_time'] / \
                        all_metrics_df['original'].str.split().str.len()
                    fig = px.histogram(
                        times_per_word,
                        title='Project-wide Time per Word Distribution',
                        labels={'value': 'Seconds per Word',
                                'count': 'Frequency'},
                        color_discrete_sequence=['#2E86C1']
                    )
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    # Editing time distribution
                    fig = px.histogram(
                        all_metrics_df,
                        x='edit_time',
                        title='Distribution of Editing Times',
                        labels={'edit_time': 'Time (seconds)',
                                'count': 'Frequency'},
                        color_discrete_sequence=['#2E86C1']
                    )
                    st.plotly_chart(fig, use_container_width=True)

        # Edit Patterns Tab
        with project_tabs[2]:
            st.subheader("Project-wide Edit Patterns")

            if not all_metrics_df.empty:
                col1, col2 = st.columns(2)

                with col1:
                    # Edit distance distribution
                    all_metrics_df['total_edits'] = all_metrics_df['insertions'] + \
                        all_metrics_df['deletions']
                    fig = px.histogram(
                        all_metrics_df,
                        x='total_edits',
                        title='Project-wide Distribution of Edit Operations',
                        labels={'total_edits': 'Number of Edits'},
                        color_discrete_sequence=['#2E86C1']
                    )
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    # Insertions vs Deletions scatter
                    fig = px.scatter(
                        all_metrics_df,
                        x='insertions',
                        y='deletions',
                        title='Project-wide Insertions vs Deletions',
                        labels={'insertions': 'Insertions',
                                'deletions': 'Deletions'},
                        color='edit_time',
                        color_continuous_scale='Viridis'
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # Additional project-wide patterns
                col1, col2 = st.columns(2)

                with col1:
                    # Edit rate over time
                    all_metrics_df['edit_rate'] = all_metrics_df['total_edits'] / \
                        all_metrics_df['original'].str.len()
                    fig = px.line(
                        all_metrics_df,
                        x=all_metrics_df.index,
                        y='edit_rate',
                        title='Edit Rate Over Time',
                        labels={'index': 'Segment Number',
                                'edit_rate': 'Edits per Character'}
                    )
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
                    # HTER distribution
                    all_metrics_df['hter'] = all_metrics_df['total_edits'] / \
                        all_metrics_df['original'].str.split().str.len()
                    fig = px.histogram(
                        all_metrics_df,
                        x='hter',
                        title='Distribution of HTER Scores',
                        labels={'hter': 'HTER Score',
                                'count': 'Frequency'},
                        color_discrete_sequence=['#2E86C1']
                    )
                    st.plotly_chart(fig, use_container_width=True)

        # Raw Data Tab
        with project_tabs[3]:
            st.subheader("Project Raw Data")

            if not all_metrics_df.empty:
                # Add user information to metrics
                all_metrics_df['user'] = all_metrics_df.apply(
                    lambda x: next(
                        (f"{user['user_name']} {user['user_surname']}"
                         for user in users_data
                         if any(m['segment_id'] == x['segment_id']
                                for m in user.get('metrics', []))),
                        'Unknown'
                    ),
                    axis=1
                )

                # Display full project metrics
                st.dataframe(
                    all_metrics_df[[
                        'user', 'segment_id', 'edit_time',
                        'insertions', 'deletions', 'total_edits',
                        'processing_speed', 'edit_rate', 'hter'
                    ]],
                    use_container_width=True
                )

                # Export options
                st.subheader("Export Project Data")
                col1, col2 = st.columns(2)

                with col1:
                    csv = all_metrics_df.to_csv(index=False)
                    st.download_button(
                        "📥 Download Project CSV",
                        data=csv,
                        file_name="project_metrics.csv",
                        mime="text/csv"
                    )

                with col2:
                    st.download_button(
                        "📥 Download Project JSON",
                        data=all_metrics_df.to_json(orient='records'),
                        file_name="project_metrics.json",
                        mime="application/json"
                    )

    # Individual Analysis Tab
    with tabs[1]:
        st.header("🎯 Individual User Analysis")

        with st.container(border=True):
            # User selector
            selected_user = st.selectbox(
                "Select User for Detailed Analysis",
                options=[
                    f"{user['user_name']} {user['user_surname']}" for user in users_data]
            )

            # Display selected user's details
            user_data = next(
                user for user in users_data
                if f"{user['user_name']} {user['user_surname']}" == selected_user
            )

            metrics = user_data.get('metrics', [])
            if metrics:
                metrics_df = pd.DataFrame(metrics)

                # Create subtabs for different analyses
                user_tabs = st.tabs([
                    "📊 Overview",
                    "⏱️ Temporal Analysis",
                    "📝 Edit Patterns",
                    "📈 Raw Data"
                ])

                # Overview Tab
                with user_tabs[0]:
                    st.subheader("User Statistics")

                    # Academic metrics for individual user
                    user_pe_effort = calculate_pe_effort(metrics)
                    user_temporal_effort = calculate_temporal_effort(metrics)

                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        st.metric(
                            "HTER",
                            f"{user_pe_effort['hter']:.3f}",
                            help="Human-targeted Translation Edit Rate"
                        )

                    with col2:
                        st.metric(
                            "Throughput",
                            f"{user_pe_effort['throughput']:.1f}",
                            help="Words processed per hour"
                        )

                    with col3:
                        st.metric(
                            "Avg Edit Distance",
                            f"{user_pe_effort['avg_edit_distance']:.2f}",
                            help="Average edits per segment"
                        )

                    with col4:
                        st.metric(
                            "Processing Speed",
                            f"{user_temporal_effort['processing_speed']:.2f}",
                            help="Characters per second"
                        )

                # Temporal Analysis Tab
                with user_tabs[1]:
                    st.subheader("Time-based Analysis")

                    # Time series of editing speed
                    metrics_df['processing_speed'] = metrics_df.apply(
                        lambda x: len(x['original']) /
                        x['edit_time'] if x['edit_time'] > 0 else 0,
                        axis=1
                    )

                    fig = px.line(
                        metrics_df,
                        x=metrics_df.index,
                        y='processing_speed',
                        title='Editing Speed Over Time',
                        labels={'index': 'Segment Number',
                                'processing_speed': 'Characters/Second'}
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # Time per word distribution
                    times_per_word = metrics_df['edit_time'] / \
                        metrics_df['original'].str.split().str.len()
                    fig = px.histogram(
                        times_per_word,
                        title='Distribution of Time per Word',
                        labels={'value': 'Seconds per Word',
                                'count': 'Frequency'},
                        color_discrete_sequence=['#2E86C1']
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # Edit Patterns Tab
                with user_tabs[2]:
                    st.subheader("Edit Pattern Analysis")

                    col1, col2 = st.columns(2)

                    with col1:
                        # Edit distance distribution
                        metrics_df['total_edits'] = metrics_df['insertions'] + \
                            metrics_df['deletions']
                        fig = px.histogram(
                            metrics_df,
                            x='total_edits',
                            title='Distribution of Edit Operations',
                            labels={'total_edits': 'Number of Edits'},
                            color_discrete_sequence=['#2E86C1']
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    with col2:
                        # Insertions vs Deletions
                        fig = px.scatter(
                            metrics_df,
                            x='insertions',
                            y='deletions',
                            title='Insertions vs Deletions',
                            labels={'insertions': 'Insertions',
                                    'deletions': 'Deletions'},
                            color='edit_time',
                            color_continuous_scale='Viridis'
                        )
                        st.plotly_chart(fig, use_container_width=True)

                # Raw Data Tab
                with user_tabs[3]:
                    st.subheader("Raw Metrics")

                    # Detailed metrics table
                    st.dataframe(
                        metrics_df[['segment_id', 'edit_time',
                                   'insertions', 'deletions', 'total_edits']],
                        use_container_width=True
                    )

                    # Export options
                    st.subheader("Export Data")
                    col1, col2 = st.columns(2)

                    with col1:
                        csv = metrics_df.to_csv(index=False)
                        st.download_button(
                            "📥 Download CSV",
                            data=csv,
                            file_name=f"{selected_user}_metrics.csv",
                            mime="text/csv"
                        )

                    with col2:
                        st.download_button(
                            "📥 Download JSON",
                            data=metrics_df.to_json(orient='records'),
                            file_name=f"{selected_user}_metrics.json",
                            mime="application/json"
                        )
            else:
                st.info("No metrics available for this user yet.")


if __name__ == "__main__":
    main()
