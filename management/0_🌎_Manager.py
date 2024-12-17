import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Optional
import pytz
from enum import Enum

# Page configuration
st.set_page_config(
    page_title="MTPE Analytics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    /* Main layout */
    .main-container { 
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }
    
    /* Header styling */
    .dashboard-header {
        padding: 1rem 0 2rem 0;
        border-bottom: 2px solid #f0f2f6;
        margin-bottom: 2rem;
    }
    
    /* Cards */
    .stat-card {
        background-color: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 1.5rem;
        border: 1px solid #f0f2f6;
        transition: transform 0.2s ease;
    }
    
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.1);
    }
    
    /* Metrics */
    .metric-container {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        margin: 0.75rem 0;
        border: 1px solid #f0f2f6;
    }
    
    /* Tables */
    .dataframe {
        width: 100%;
        margin: 1rem 0;
        border-collapse: separate;
        border-spacing: 0;
        border: 1px solid #f0f2f6;
        border-radius: 8px;
    }
    
    .dataframe th {
        background-color: #f8f9fa;
        padding: 12px 15px;
        border-bottom: 2px solid #e9ecef;
    }
    
    .dataframe td {
        padding: 10px 15px;
        border-bottom: 1px solid #f0f2f6;
    }
    
    /* Charts */
    .chart-container {
        background-color: white;
        padding: 1.5rem;
        border-radius: 12px;
        margin: 1.5rem 0;
        border: 1px solid #f0f2f6;
    }
    
    /* Filters */
    .filter-container {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        border: 1px solid #f0f2f6;
    }
    
    /* Buttons */
    .stButton button {
        border-radius: 8px;
        padding: 0.5rem 1rem;
        transition: all 0.2s ease;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        padding: 0.5rem;
    }
    
    .stTabs [data-baseweb="tab"] {
        padding: 0.5rem 1rem;
        border-radius: 8px;
    }
    
    /* Warning/Info boxes */
    .stAlert {
        border-radius: 12px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)

def connect_to_mongodb():
    """Establish connection to MongoDB"""
    connection_string = st.secrets["MONGO_CONNECTION_STRING"]
    client = MongoClient(connection_string, tlsAllowInvalidCertificates=True)
    return client['mtpe_database']

def get_user_metrics() -> pd.DataFrame:
    """Retrieve and process user metrics from MongoDB"""
    db = connect_to_mongodb()
    collection = db['user_progress']
    
    # Get all user progress documents
    user_data = list(collection.find())
    
    if not user_data:
        return pd.DataFrame()
    
    # Process and flatten metrics data
    processed_data = []
    for doc in user_data:
        if 'metrics' in doc:
            for metric in doc['metrics']:
                metric['user_name'] = doc['user_name']
                metric['user_surname'] = doc['user_surname']
                metric['timestamp'] = doc.get('last_updated', datetime.now())
                processed_data.append(metric)
    
    return pd.DataFrame(processed_data)

def main():
    # Header with description
    st.markdown('<div class="dashboard-header">', unsafe_allow_html=True)
    st.title("📊 MTPE Analytics Dashboard")
    st.markdown("""
    Welcome to the Machine Translation Post-Editing Analytics Dashboard. 
    Monitor translator performance, analyze segments, and manage user data all in one place.
    """)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Get data first
    df = get_user_metrics()
    if df.empty:
        st.info("🔍 No MTPE data available. Users need to complete some translations first.")
        return
    
    # Main tabs with icons
    tab1, tab2, tab3 = st.tabs([
        "📈 Translator Performance",
        "🔍 Segment Analysis",
        "👥 User Management"
    ])
    
    with tab1:
        st.markdown("""
        <div class="metric-container">
            <h3>Translator Performance Overview</h3>
            <p>Compare productivity metrics and efficiency across all translators.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Calculate comprehensive user statistics
        user_stats = df.groupby(['user_name', 'user_surname']).agg({
            'edit_time': ['mean', 'sum'],
            'insertions': ['mean', 'sum'],
            'deletions': ['mean', 'sum'],
            'segment_id': 'count',
            'original': lambda x: sum(len(text.split()) for text in x)
        }).reset_index()

        # Flatten column names
        user_stats.columns = ['Name', 'Surname', 'Avg Time/Segment', 'Total Time', 
                            'Avg Insertions', 'Total Insertions',
                            'Avg Deletions', 'Total Deletions', 
                            'Segments Completed', 'Words Processed']
        
        # Calculate additional metrics
        user_stats['Words/Hour'] = (user_stats['Words Processed'] / 
                                  (user_stats['Total Time'] / 3600))
        user_stats['Edits/Segment'] = ((user_stats['Total Insertions'] + 
                                      user_stats['Total Deletions']) / 
                                      user_stats['Segments Completed'])
        
        # Display formatted statistics
        st.dataframe(
            user_stats.style.format({
                'Avg Time/Segment': '{:.1f}s',
                'Total Time': '{:.1f}s',
                'Avg Insertions': '{:.1f}',
                'Avg Deletions': '{:.1f}',
                'Words/Hour': '{:.1f}',
                'Edits/Segment': '{:.1f}'
            }),
            use_container_width=True
        )
    
    with tab2:
        st.markdown("""
        <div class="metric-container">
            <h3>Detailed Segment Analysis</h3>
            <p>Search and analyze individual translation segments and their modifications.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Enhanced filter layout
        with st.container():
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                search_term = st.text_input("🔍 Search in segments", placeholder="Enter text to search...")
            with col2:
                min_edits = st.number_input("Minimum edits", value=0, min_value=0)
            with col3:
                st.markdown("###")  # Spacing
                if st.button("Reset Filters", type="secondary"):
                    search_term = ""
                    min_edits = 0
            
            # Create a copy of df for filtering
            filtered_df = df.copy()
            
            # Apply filters
            if search_term:
                segment_mask = (
                    filtered_df['original'].str.contains(search_term, case=False) |
                    filtered_df['edited'].str.contains(search_term, case=False)
                )
                filtered_df = filtered_df[segment_mask]
            
            if min_edits > 0:
                filtered_df = filtered_df[
                    (filtered_df['insertions'] + filtered_df['deletions']) >= min_edits
                ]
            
            # Display segments with key information
            segment_data = filtered_df[[
                'user_name', 'segment_id', 'original', 'edited', 
                'edit_time', 'insertions', 'deletions'
            ]].copy()
            
            segment_data['total_edits'] = segment_data['insertions'] + segment_data['deletions']
            
            st.dataframe(
                segment_data.style.format({
                    'edit_time': '{:.1f}s'
                }),
                use_container_width=True
            )
    
    with tab3:
        st.markdown("""
        <div class="metric-container">
            <h3>User Management Console</h3>
            <p>Manage translator accounts and their associated data.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Enhanced warning message
        st.warning("""
        ⚠️ **Data Deletion Warning**
        
        Please note that deleting user data is a permanent action and cannot be undone.
        Make sure you have necessary backups before proceeding.
        """)
        
        # Get users list
        users = df[['user_name', 'user_surname']].drop_duplicates().to_dict('records')

        if not users:
            st.error("No users found in the database.")
            return

        # Initialize session state for confirmation
        if 'confirm_delete' not in st.session_state:
            st.session_state.confirm_delete = None

        # Create a table of users with delete buttons
        for user in users:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.write(f"**{user['user_name']} {user['user_surname']}**")

                with col2:
                    user_id = f"{user['user_name']}_{user['user_surname']}"

                    # If this user is pending confirmation
                    if st.session_state.confirm_delete == user_id:
                        if st.button("⚠️ Click to Confirm",
                                   key=f"confirm_{user_id}",
                                   type="primary",
                                   use_container_width=True):
                            # Perform deletion
                            db = connect_to_mongodb()
                            collection = db['user_progress']
                            result = collection.delete_one({
                                'user_name': user['user_name'],
                                'user_surname': user['user_surname']
                            })
                            
                            if result.deleted_count > 0:
                                st.success(f"Data for {user['user_name']} {user['user_surname']} deleted successfully!")
                                st.session_state.confirm_delete = None
                                st.rerun()
                            else:
                                st.error("Failed to delete user data. Please try again.")
                                st.session_state.confirm_delete = None
                    else:
                        # Show initial delete button
                        if st.button("🗑️ Delete Data",
                                   key=f"delete_{user_id}",
                                   type="secondary",
                                   use_container_width=True):
                            st.session_state.confirm_delete = user_id
                            st.rerun()

if __name__ == "__main__":
    main()
