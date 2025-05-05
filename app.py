import streamlit as st
st.set_page_config(layout="wide")

# 1) Ask for the code once
if "role" not in st.session_state:
    st.title("🔐 Enter Quiz Code")
    code = st.text_input("Please enter the host password or game pin:", type="password")
    if st.button("Join"):
        host_pwd = st.secrets["host_password"]
        game_pin  = st.secrets["game_pin"]

        if code == host_pwd:
            st.session_state.role = "host"
            st.rerun()        # ← rerun immediately
        elif code == game_pin:
            st.session_state.role = "player"
            st.rerun()        # ← rerun immediately
        else:
            st.error("❌ Invalid code. Try again.")
    st.stop()

# 2) Now that we have a role, we can import and initialize Firestore
import json, firebase_admin
from firebase_admin import credentials, firestore
from streamlit_autorefresh import st_autorefresh

firebase_creds = st.secrets["firebase_service_account"].to_dict()
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)
db = firestore.client()

cur_ref = db.document("game_state/current")
if not cur_ref.get().exists:
    # Initialize to question 0 so players immediately see Q1
    cur_ref.set({"current_index": 0})

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

# ─── 2. App Configuration ─────────────────────────────────────────────────────
if st.session_state.role == "host":
    st.title("🔧 Quiz Host Controller")

    # ─── 0) Auto-refresh every 2 seconds ──────────────────────────────
    st_autorefresh(interval=2000, key="host_refresh")

    # ─── 1) Load questions & current index ────────────────────────────
    questions = load_questions()
    total_q  = len(questions)
    if "host_idx" not in st.session_state:
        st.session_state.host_idx = get_current_index()
    idx = st.session_state.host_idx

    # ─── 2) Show the current question ─────────────────────────────────
    st.markdown(f"### Question {idx+1} / {total_q}")
    q = questions[idx]
    st.write(q["text"])
    if q["type"] == "mc":
        for opt in q["options"]:
            st.write(f"- {opt}")

    # ─── 3) Advance button ────────────────────────────────────────────
    if st.button("➡️ Next Question"):
        new_idx = (idx + 1) % total_q
        st.session_state.host_idx = new_idx
        set_current_index(new_idx)
        st.experimental_rerun()

    # ─── 4) Student Responses ──────────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 Student Responses (Raw)")

    # Fetch ALL responses for this question, ordered by timestamp
    resp_docs = (
        db.collection("responses")
          .where("question_id", "==", idx)
          .order_by("timestamp")
          .stream()
    )

    rows = []
    for d in resp_docs:
        r = d.to_dict()
        ts = r.get("timestamp")
        # Convert Firestore timestamp to readable string
        ts_str = (
            ts.ToDatetime().strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(ts, "ToDatetime")
            else str(ts)
        )
        rows.append({
            "Nickname":  r["nickname"],
            "Answer":    r["answer"],
            "Timestamp": ts_str
        })

    if rows:
        # st.dataframe will let you scroll if it gets long
        st.dataframe(rows, height=300)
    else:
        st.write("No responses submitted yet for this question.")
    
elif st.session_state.role == "player":
    # ─── Player View ───────────────────────────────────────────────────────
    st.title("🕹️ Quiz Player")
    nick = st.text_input("Enter your nickname", key="nick")
    if not nick:
        st.info("Please choose a nickname to join the game.")
        st.stop()

    # ←––– This will rerun the script every 2 seconds
    st_autorefresh(interval=2000, key="player_refresh")

    # On each run, fetch the latest question index
    current_idx = get_current_index()

    # Load that question
    q_doc = db.collection("questions").document(str(current_idx)).get()
    if not q_doc.exists:
        st.error("No question found for index " + str(current_idx))
        st.stop()
    q = q_doc.to_dict()

    # Render it
    st.markdown(f"### Q{current_idx+1}. {q['text']}")
    if q["type"] == "mc":
        choice = st.radio("Choose one:", q["options"], key=f"mc_{current_idx}")
    else:
        choice = st.text_input("Your answer:", key=f"text_{current_idx}")

    # Submission button
    if st.button("Submit Answer", key=f"submit_{current_idx}"):
        db.collection("responses").add({
            "question_id": current_idx,
            "nickname": nick,
            "answer": choice,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        st.success("✅ Answer submitted!")
