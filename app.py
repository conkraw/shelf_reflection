import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(layout="wide")

# ─── 1. Initialize Firestore ──────────────────────────────────────────────────
firebase_creds = st.secrets["firebase_service_account"].to_dict()
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ─── 2) Helpers ───────────────────────────────────────────────────────────────
def load_questions():
    """
    Attempts to load all docs from the `questions` collection,
    ordered by name (i.e. "0", "1", "2", ...).
    Returns a list of dicts, or raises a clear exception.
    """
    try:
        docs = db.collection("questions").order_by("__name__").stream()
        questions = []
        for doc in docs:
            data = doc.to_dict()
            if data is None:
                st.warning(f"Document {doc.id} has no data.")
                continue
            questions.append(data)
        if not questions:
            st.warning("⚠️ No questions found in Firestore – check your collection name and rules.")
        return questions

    except Exception as e:
        # Show the error in the app so you can see exactly what's wrong
        st.error(f"❌ Failed to load questions from Firestore:\n{e}")
        # Stop the app here so you don’t run into downstream indexing errors
        st.stop()


# ─── 2. App Configuration ─────────────────────────────────────────────────────

mode = st.sidebar.selectbox("Mode", ["Host ▶️", "Player 🎮"], key="app_mode" )

# ─── 3. Data Model Helpers ────────────────────────────────────────────────────
def get_current_index():
    doc_ref = db.document("game_state/current")
    doc = doc_ref.get()
    if not doc.exists:
        # no game_state yet → start at 0
        return 0
    data = doc.to_dict() or {}
    return data.get("current_index", 0)

def set_current_index(idx):
    db.document("game_state/current").set({"current_index": idx})


# ─── 3) Main App ──────────────────────────────────────────────────────────────
mode = st.sidebar.selectbox("Mode", ["Host ▶️", "Player 🎮"])

if mode == "Host ▶️":
    st.title("🔧 Quiz Host Controller")

    # this will either return a list or stop the app with an error
    questions = load_questions()
    total_q  = len(questions)

    # Safely grab or initialize the host’s question index
    if "host_idx" not in st.session_state:
        # defaults to 0 if the doc doesn’t exist
        doc = db.document("game_state/current").get()
        st.session_state.host_idx = (doc.to_dict() or {}).get("current_index", 0)

    # Show the current question
    idx = st.session_state.host_idx
    st.markdown(f"### Question {idx+1} / {total_q}")
    q = questions[idx]
    st.write(q["text"])
    if q["type"] == "mc":
        for opt in q["options"]:
            st.write(f"- {opt}")

    if st.button("➡️ Next Question"):
        new_idx = (idx + 1) % total_q
        st.session_state.host_idx = new_idx
        db.document("game_state/current").set({"current_index": new_idx})
        st.experimental_rerun()

# ─── 5. Player View ───────────────────────────────────────────────────────────
else:
    st.title("🕹️ Quiz Player")
    nick = st.text_input("Enter your nickname", key="nick")
    if not nick:
        st.info("Please choose a nickname to join the game.")
        st.stop()

    placeholder = st.empty()

    def on_state_change(doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            idx = doc.to_dict()["current_index"]
            q_doc = db.collection("questions").document(str(idx)).get()
            q = q_doc.to_dict()

            with placeholder.container():
                st.markdown(f"### Q{idx+1}. {q['text']}")
                if q["type"] == "mc":
                    choice = st.radio("Choose one:", q["options"], key=f"mc_{idx}")
                else:
                    choice = st.text_input("Your answer:", key=f"text_{idx}")

                if st.button("Submit Answer", key=f"submit_{idx}"):
                    db.collection("responses").add({
                        "question_id": idx,
                        "nickname": nick,
                        "answer": choice,
                        "timestamp": firestore.SERVER_TIMESTAMP
                    })
                    st.success("Answer submitted!")

    if "listener" not in st.session_state:
        state_ref = db.document("game_state/current")
        st.session_state.listener = state_ref.on_snapshot(on_state_change)

    st.write("⏳ Waiting for host to advance questions…")

