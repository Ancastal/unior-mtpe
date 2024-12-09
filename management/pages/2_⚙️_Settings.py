import sys
from pathlib import Path
import streamlit as st
from pymongo import MongoClient
from enum import Enum

# Add the parent directory to the Python path
root_path = Path(__file__).parent.parent
sys.path.append(str(root_path))


class UserRole(Enum):
    ADMIN = "admin"
    USER = "user"


def connect_to_mongodb():
    """Connect to MongoDB database"""
    connection_string = st.secrets["MONGO_CONNECTION_STRING"]
    client = MongoClient(
        connection_string,
        tlsAllowInvalidCertificates=True
    )
    return client['mtpe_database']


# Page config
st.set_page_config(
    page_title="Settings - MTPE Manager",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)


def login_required(func):
    """Decorator to require login for certain pages/functions"""
    def wrapper(*args, **kwargs):
        if "user" not in st.session_state:
            st.warning("Please log in to access this page.")
            st.switch_page("0_🌎_Manager.py")
            return
        return func(*args, **kwargs)
    return wrapper


@login_required
def main():
    # Create a clean header with a subtle separator
    st.title("⚙️ Settings")
    st.markdown("---")

    # Create tabs for better organization
    tabs = st.tabs(["🎨 Preferences", "👤 Account", "ℹ️ About"])

    # Preferences Tab
    with tabs[0]:
        st.header("Customize Your Experience")

        # Create two columns for preferences
        pref_col1, pref_col2 = st.columns(2)

        with pref_col1:
            st.subheader("🎭 Theme Settings")
            st.caption("Choose how MTPE Manager looks to you")
            theme = st.selectbox(
                "Select theme",
                ["System Default", "Light", "Dark"],
                key="theme"
            )

        with pref_col2:
            st.subheader("🌐 Language Settings")
            st.caption("Choose your preferred language")
            language = st.selectbox(
                "Select language",
                ["English", "Italiano", "Español"],
                key="language"
            )

        # Add a notice about settings taking effect
        with st.expander("ℹ️ About Settings"):
            st.info(
                "Theme and language changes will take effect after you refresh the page.",
                icon="ℹ️"
            )

    # Account Tab
    with tabs[1]:
        st.header("Account Information")

        # Get user info
        user = st.session_state["user"]

        # Create a metric container for user info
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                label="Account Status",
                value="Active" if user['active'] else "Inactive"
            )

        with col2:
            st.metric(
                label="Role",
                value=user['role'].title()
            )

        with col3:
            st.metric(
                label="Language",
                value=st.session_state.get('language', 'English')
            )

        # Detailed user information in an expander
        with st.expander("📋 Detailed Information"):
            st.text_input(
                "Full Name", value=f"{user['name']} {user['surname']}", disabled=True)
            st.text_input("Email", value=user['email'], disabled=True)

        # Session management
        st.divider()
        st.subheader("Session Management")
        if st.button("🚪 Logout", type="primary", use_container_width=True):
            del st.session_state["user"]
            st.switch_page("0_🌎_Manager.py")

    # About Tab
    with tabs[2]:
        st.header("About MTPE Manager")

        # Version information
        version_col1, version_col2 = st.columns(2)

        with version_col1:
            st.metric(label="Version", value="1.0")
            st.caption("Released: January 2024")

        with version_col2:
            st.metric(label="Status", value="Stable")
            st.caption("Last updated: March 2024")

        # Contact information
        st.divider()
        st.subheader("Support")
        st.write("For assistance, please contact our support team:")
        st.code("support@example.com", language=None)

        # Credits
        st.divider()
        st.caption("© 2024 MTPE Manager. All rights reserved.")
        st.caption("Made with Streamlit")


if __name__ == "__main__":
    main()
