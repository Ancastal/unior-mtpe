import streamlit as st
import pandas as pd
from pathlib import Path
import sys
import sacrebleu
from typing import List, Tuple
import numpy as np
from io import StringIO
from pymongo import AsyncMongoClient
import asyncio
from comet import download_model, load_from_checkpoint
from bert_score import BERTScorer
from nltk.translate.meteor_score import meteor_score
import nltk
from nltk.tokenize import word_tokenize
from functools import lru_cache
import torch

# Add the parent directory to the Python path
root_path = Path(__file__).parent.parent
sys.path.append(str(root_path))

# Page config
st.set_page_config(
    page_title="Evaluation - MTPE Manager",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Cache NLTK downloads


@st.cache_resource
def download_nltk_data():
    """Cache NLTK data downloads"""
    nltk.download('wordnet')
    nltk.download('punkt')


# Replace the existing NLTK downloads with:
download_nltk_data()

# Add these cached model loaders after the imports


@st.cache_resource
def load_bert_scorer():
    """Cache BERTScorer model loading"""
    return BERTScorer(lang="en", rescale_with_baseline=True)


@st.cache_resource
def load_comet_model():
    """Cache COMET model loading"""
    model_path = download_model("Unbabel/wmt22-comet-da")
    model = load_from_checkpoint(model_path)
    return model


@st.cache_resource
def get_cached_mongo_client():
    """Cache MongoDB client connection"""
    connection_string = st.secrets["MONGO_CONNECTION_STRING"]
    return AsyncMongoClient(connection_string, tlsAllowInvalidCertificates=True)


async def get_mongo_connection():
    """Get MongoDB connection using cached client"""
    client = get_cached_mongo_client()
    return client['mtpe_database']


async def get_users():
    """Retrieve list of users from MongoDB"""
    db = await get_mongo_connection()
    collection = db['user_progress']

    users = []
    cursor = collection.find({}, {'user_name': 1, 'user_surname': 1})
    async for doc in cursor:
        if 'user_name' in doc and 'user_surname' in doc:
            users.append({
                'name': doc['user_name'],
                'surname': doc['user_surname']
            })

    return users


async def get_post_edited_translations(user_name: str, user_surname: str):
    """Retrieve post-edited translations from MongoDB for specific user"""
    db = await get_mongo_connection()
    collection = db['user_progress']

    # Find specific user's progress
    doc = await collection.find_one({
        'user_name': user_name,
        'user_surname': user_surname
    })

    if doc and 'metrics' in doc:
        # Extract post-edited translations from metrics instead of full_text
        # This ensures we get only the edited translations
        metrics = sorted(doc['metrics'], key=lambda x: x['segment_id'])
        return [m['edited'] for m in metrics]

    return []


def calculate_metrics(references: List[str], hypotheses: List[str]) -> Tuple[float, float, float]:
    """Calculate BLEU, chrF, and TER scores"""
    # BLEU score
    bleu = sacrebleu.corpus_bleu(hypotheses, [references])

    # chrF score
    chrf = sacrebleu.corpus_chrf(hypotheses, [references])

    # TER score
    ter = sacrebleu.corpus_ter(hypotheses, [references])

    return bleu.score, chrf.score, ter.score


def process_file(uploaded_file) -> pd.DataFrame:
    """Process uploaded reference file and return a DataFrame"""
    df = None
    if uploaded_file.name.endswith('.txt'):
        # Read text file line by line
        content = uploaded_file.getvalue().decode('utf-8')
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        df = pd.DataFrame({'reference': lines})
    elif uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    elif uploaded_file.name.endswith(('.xls', '.xlsx')):
        df = pd.read_excel(uploaded_file)

    if df is None:
        raise ValueError("Unsupported file format")
    return df


async def delete_user_data(user_name: str, user_surname: str) -> bool:
    """Delete user data from MongoDB"""
    try:
        db = await get_mongo_connection()
        collection = db['user_progress']
        result = await collection.delete_one({
            'user_name': user_name,
            'user_surname': user_surname
        })
        return result.deleted_count > 0
    except Exception as e:
        st.error(f"Error deleting user data: {str(e)}")
        return False


def calculate_additional_metrics(references: List[str], hypotheses: List[str], selected_metrics: List[str]) -> dict:
    """Calculate selected metrics for the translations"""
    results = {}

    # Initialize models as None
    bert_scorer = None
    comet_model = None

    # Pre-load models if needed
    if "BERTScore" in selected_metrics:
        bert_scorer = load_bert_scorer()
    if "COMET" in selected_metrics:
        comet_model = load_comet_model()

    for metric in selected_metrics:
        if metric == "BLEU":
            bleu = sacrebleu.corpus_bleu(hypotheses, [references])
            results["BLEU"] = bleu.score

        elif metric == "chrF":
            chrf = sacrebleu.corpus_chrf(hypotheses, [references])
            results["chrF"] = chrf.score

        elif metric == "TER":
            ter = sacrebleu.corpus_ter(hypotheses, [references])
            results["TER"] = ter.score

        elif metric == "METEOR":
            meteor_scores = [meteor_score([word_tokenize(ref)], word_tokenize(hyp))
                             for ref, hyp in zip(references, hypotheses)]
            results["METEOR"] = np.mean(meteor_scores) * 100

        elif metric == "BERTScore" and bert_scorer is not None:
            P, R, F1 = bert_scorer.score(hypotheses, references)
            results["BERTScore"] = F1.mean().item() * 100

        elif metric == "COMET" and comet_model is not None:
            all_scores = []
            for batch in batch_process(list(zip(hypotheses, references))):
                batch_hyp, batch_ref = zip(*batch)
                data = [{"src": "", "mt": hyp, "ref": ref}
                        for hyp, ref in zip(batch_hyp, batch_ref)]
                batch_scores = comet_model.predict(data, batch_size=8, gpus=0)
                all_scores.extend(batch_scores)
            results["COMET"] = np.mean(all_scores) * 100

    return results


def batch_process(items, batch_size=32):
    """Process items in batches"""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def main():
    st.title("📊 Translation Evaluation")
    st.markdown("---")

    # Create tabs for different evaluation modes
    tabs = st.tabs(["📈 Metrics Calculation", "📊 Translation Management"])

    # Metrics Calculation Tab
    with tabs[0]:

        # User selection section
        st.subheader("👤 Select User")
        users = asyncio.run(get_users())

        if not users:
            st.error("No users found in the database.")
            return

        # Create user selection dropdown
        user_options = [f"{user['name']} {user['surname']}" for user in users]
        selected_user = st.selectbox(
            "Select user to evaluate",
            options=user_options
        )

        # Split selected user into name and surname
        selected_name, selected_surname = selected_user.split(' ', 1)

        with st.container():
            st.caption("""
            Upload your reference translations to calculate quality metrics against post-edited translations.
            Supported file formats: CSV, Excel, TXT (tab-separated)
            """)

            # File upload section
            st.subheader("📄 Reference Translations")
            reference_file = st.file_uploader(
                "Upload reference file",
                type=['csv', 'xlsx', 'xls', 'txt'],
                key="reference_upload"
            )

            if reference_file:
                try:
                    # Process reference file
                    ref_df = process_file(reference_file)

                    # Get post-edited translations from MongoDB for selected user
                    post_edited = asyncio.run(get_post_edited_translations(
                        selected_name, selected_surname))

                    if not post_edited:
                        st.error(
                            f"No post-edited translations found for {selected_user}.")
                        return

                    # Get references directly from the 'reference' column
                    references = ref_df['reference'].tolist()

                    # Ensure we have matching number of translations
                    if len(references) != len(post_edited):
                        st.error(f"Number of reference translations ({len(references)}) does not match "
                                 f"number of post-edited translations ({len(post_edited)})")
                        return

                    # Metric selection using pills
                    st.subheader("Select Metrics")

                    available_metrics = ["BLEU", "chrF",
                                         "TER", "METEOR", "BERTScore", "COMET"]
                    selected_metrics = st.pills(
                        "Select metrics to calculate",
                        available_metrics,
                        selection_mode="multi",
                        help="You can select multiple metrics to compare translations"
                    )

                    if st.button("Calculate Metrics", type="primary", use_container_width=True):
                        with st.spinner("Calculating metrics..."):
                            results = calculate_additional_metrics(
                                references, post_edited, selected_metrics)

                            # Display results
                            st.subheader("📊 Results")

                            # Create columns based on number of selected metrics
                            cols = st.columns(len(results))

                            # Display metrics in columns
                            for col, (metric_name, score) in zip(cols, results.items()):
                                with col:
                                    help_text = {
                                        "BLEU": "Higher is better (0-100)",
                                        "chrF": "Higher is better (0-100)",
                                        "TER": "Lower is better",
                                        "METEOR": "Higher is better (0-100)",
                                        "BERTScore": "Higher is better (0-100)",
                                        "COMET": "Higher is better (-inf to 100)"
                                    }
                                    st.metric(
                                        metric_name,
                                        f"{score:.2f}",
                                        help=help_text.get(metric_name, "")
                                    )

                except Exception as e:
                    st.error(f"Error processing data: {str(e)}")
                    st.info(
                        "Please make sure your reference file has the correct format.")

    # Results History Tab
    with tabs[1]:
        st.header("User Management")

        # Get users list
        users = asyncio.run(get_users())

        if not users:
            st.error("No users found in the database.")
            return

        st.warning(
            "⚠️ Warning: Deleting user data is permanent and cannot be undone!")

        # Initialize session state for confirmation
        if 'confirm_delete' not in st.session_state:
            st.session_state.confirm_delete = None

        # Create a table of users with delete buttons
        for user in users:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.write(f"**{user['name']} {user['surname']}**")

                with col2:
                    user_id = f"{user['name']}_{user['surname']}"

                    # If this user is pending confirmation
                    if st.session_state.confirm_delete == user_id:
                        if st.button("⚠️ Click to Confirm",
                                     key=f"confirm_{user_id}",
                                     type="primary",
                                     use_container_width=True):
                            # Perform deletion
                            if asyncio.run(delete_user_data(user['name'], user['surname'])):
                                st.success(
                                    f"Data for {user['name']} {user['surname']} deleted successfully!")
                                st.session_state.confirm_delete = None
                                st.rerun()
                            else:
                                st.error(
                                    "Failed to delete user data. Please try again.")
                                st.session_state.confirm_delete = None
                    else:
                        # Show initial delete button
                        if st.button("🗑️ Delete Data",
                                     key=f"delete_{user_id}",
                                     type="secondary",
                                     use_container_width=True):
                            st.session_state.confirm_delete = user_id
                            st.rerun()

    with st.spinner("Loading models... This may take a moment on first run."):
        # Pre-load commonly used models
        if torch.cuda.is_available():
            st.info("GPU detected! Using GPU acceleration for metrics calculation.")
        download_nltk_data()


if __name__ == "__main__":
    main()
