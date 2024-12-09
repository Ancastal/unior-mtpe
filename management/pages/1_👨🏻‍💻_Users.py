import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import datetime
import pytz
import hashlib
import secrets
from enum import Enum
import sys
from pathlib import Path


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


def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def generate_salt() -> str:
    """Generate a random salt for password hashing"""
    return secrets.token_hex(16)


# Add the parent directory to the Python path to import from manager.py
sys.path.append(str(Path(__file__).parent.parent))

# Page config
st.set_page_config(
    page_title="User Management - MTPE Manager",
    page_icon="👥",
    layout="wide",
    initial_sidebar_state="expanded"
)


def create_user(email: str, password: str, name: str, surname: str, role: UserRole = UserRole.USER) -> bool:
    """Create a new user if the database"""
    db = connect_to_mongodb()
    users = db['users']

    # Check if user already exists
    if users.find_one({"email": email}):
        return False

    salt = generate_salt()
    hashed_password = hash_password(password + salt)

    user = {
        "email": email,
        "password_hash": hashed_password,
        "salt": salt,
        "name": name,
        "surname": surname,
        "role": role.value,
        "created_at": datetime.now(pytz.UTC),
        "active": True
    }

    users.insert_one(user)
    return True


def update_user(email: str, updates: dict) -> bool:
    """Update user data"""
    db = connect_to_mongodb()
    users = db['users']

    if 'password' in updates:
        salt = generate_salt()
        updates['password_hash'] = hash_password(
            updates.pop('password') + salt)
        updates['salt'] = salt

    result = users.update_one(
        {"email": email},
        {"$set": updates}
    )
    return result.modified_count > 0


def deactivate_user(email: str) -> bool:
    """Deactivate a user (soft delete)"""
    return update_user(email, {"active": False})


def admin_required(func):
    """Decorator to require admin role for certain pages/functions"""
    def wrapper(*args, **kwargs):
        if "user" not in st.session_state:
            st.warning("Please log in to access this page.")
            st.switch_page("0_🌎_Manager.py")
            return
        if st.session_state["user"]["role"] != UserRole.ADMIN.value:
            st.error("Admin access required.")
            st.switch_page("0_🌎_Manager.py")
            return
        return func(*args, **kwargs)
    return wrapper


@admin_required
def main():
    # Create a clean header with a subtle separator
    st.title("👥 User Management")
    st.markdown("---")

    # Create tabs for better organization
    tabs = st.tabs(["➕ Create User", "👥 Manage Users"])

    # Create User Tab
    with tabs[0]:
        st.header("Create New User")

        with st.container():
            st.caption("Add a new user to the system")

            with st.form("create_user_form", clear_on_submit=True):
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("📝 Basic Information")
                    email = st.text_input(
                        "Email", placeholder="user@example.com")
                    name = st.text_input("First Name", placeholder="John")
                    surname = st.text_input("Last Name", placeholder="Doe")

                with col2:
                    st.subheader("🔐 Access Control")
                    password = st.text_input("Password", type="password")
                    role = st.selectbox(
                        "Role",
                        [role.value for role in UserRole],
                        help="Select the user's role in the system"
                    )

                submit_col1, submit_col2 = st.columns([3, 1])
                with submit_col2:
                    submit_button = st.form_submit_button(
                        "Create User",
                        type="primary",
                        use_container_width=True
                    )

                if submit_button:
                    if not all([email, password, name, surname]):
                        st.error("Please fill in all fields")
                    elif create_user(email, password, name, surname, UserRole(role)):
                        st.success("✅ User created successfully")
                        st.balloons()
                    else:
                        st.error("❌ User already exists")

    # Manage Users Tab
    with tabs[1]:
        st.header("Manage Existing Users")

        # Get users from database
        db = connect_to_mongodb()
        users = list(db['users'].find({}, {"password_hash": 0, "salt": 0}))

        if users:
            # Add search/filter functionality
            search = st.text_input("🔍 Search users by name or email")

            # Filter users based on search
            filtered_users = users
            if search:
                search = search.lower()
                filtered_users = [
                    user for user in users
                    if search in user['name'].lower() or
                    search in user['surname'].lower() or
                    search in user['email'].lower()
                ]

            # Display user count
            st.caption(f"Showing {len(filtered_users)} of {len(users)} users")

            # Create columns for filtering
            filter_col1, filter_col2, _ = st.columns([1, 1, 2])
            with filter_col1:
                role_filter = st.multiselect(
                    "Filter by role",
                    options=list(set(user['role'] for user in users))
                )
            with filter_col2:
                status_filter = st.multiselect(
                    "Filter by status",
                    options=["Active", "Inactive"]
                )

            # Apply filters
            if role_filter:
                filtered_users = [
                    u for u in filtered_users if u['role'] in role_filter]
            if status_filter:
                filtered_users = [
                    u for u in filtered_users
                    if ("Active" in status_filter and u['active']) or
                       ("Inactive" in status_filter and not u['active'])
                ]

            # Display users in expandable containers
            for user in filtered_users:
                with st.expander(
                    f"{'🟢' if user['active'] else '🔴'} {user['name']} {user['surname']} ({user['email']})"
                ):
                    col1, col2, col3 = st.columns([2, 2, 1])

                    with col1:
                        st.metric("Role", user['role'].title())
                        st.caption(
                            f"Created: {user['created_at'].strftime('%Y-%m-%d %H:%M:%S')}")

                    with col2:
                        st.metric(
                            "Status",
                            "Active" if user['active'] else "Inactive"
                        )

                    with col3:
                        if user['active']:
                            if st.button(
                                "🚫 Deactivate",
                                key=f"deactivate_{user['email']}",
                                type="secondary",
                                use_container_width=True
                            ):
                                if deactivate_user(user['email']):
                                    st.success("User deactivated successfully")
                                    st.rerun()
        else:
            st.info("👤 No users found in the system")
            st.caption("Create a new user to get started")


if __name__ == "__main__":
    main()
