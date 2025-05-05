import streamlit as st
import json
import time
import threading

import firebase_admin
from firebase_admin import credentials, firestore

# ─── 1. Initialize Firestore ──────────────────────────────────────────────────
if not firebase_admin._apps:
    sa_json = json.loads(st.secrets["firebase"]["service_account"])
    cred    = credentials.Certificate(sa_json)
    firebase_admin.initialize_app(cred)
db = firestore.client()


# ─── 2. App Configuration ─────────────────────────────────────────────────────
st.set_page_config(layout="wide")
mode = st.sidebar.selectbox("Mode", ["Host ▶️", "Player 🎮"])


# ─── 3. Data Model Helpers ────────────────────────────────────────────────────
def load_questions():
    docs = db.collection("questions").order_by("__name__").stream()
    return [q.to_dict() for q in docs]

def get_current_index():
    doc = db.document("game_state/current").get()
    return doc.to_dict().get("current_index", 0)

def set_current_index(idx):
    db.document("game_state/current").set({"current_index": idx})


# ─── 4. Host View ─────────────────────────────────────────────────────────────
if mode == "Host ▶️":
    st.title("🔧 Quiz Host Controller")

    # Load questions once
    questions = load_questions()
    total_q = len(questions)

    # Persist host’s local index
    if "host_idx" not in st.session_state:
        st.session_state.host_idx = get_current_index()

    st.markdown(f"### Question {st.session_state.host_idx+1} / {total_q}")
    q = questions[st.session_state.host_idx]
    st.write(q["text"])
    if q["type"] == "mc":
        for o in q["options"]:
            st.write(f"- {o}")

    if st.button("➡️ Next Question"):
        new_idx = (st.session_state.host_idx + 1) % total_q
        st.session_state.host_idx = new_idx
        set_current_index(new_idx)
        st.experimental_rerun()

    st.markdown("---")
    st.subheader("🏆 Leaderboard (Current Q)")
    # Simple leaderboard: count correct MC answers for current question
    resp_docs = db.collection("responses").where("question_id", "==", st.session_state.host_idx).stream()
    scores = {}
    for d in resp_docs:
        r = d.to_dict()
        nick = r["nickname"]
        ans  = r["answer"]
        correct = (ans == q.get("ans")) if q["type"]=="mc" else False
        scores[nick] = scores.get(nick, 0) + (1 if correct else 0)
    if scores:
        st.table(
            sorted(scores.items(), key=lambda x: -x[1]),
            columns=["Nickname","Points"]
        )
    else:
        st.write("No responses yet.")


# ─── 5. Player View ───────────────────────────────────────────────────────────
else:
    st.title("🕹️ Quiz Player")
    nick = st.text_input("Enter your nickname", key="nick")
    if not nick:
        st.info("Please choose a nickname to join the game.")
        st.stop()

    placeholder = st.empty()

    # Callback for Firestore real‐time updates
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
    # Attach listener once
    if "listener" not in st.session_state:
        state_ref = db.document("game_state/current")
        st.session_state.listener = state_ref.on_snapshot(on_state_change)

    st.write("⏳ Waiting for host to advance questions…")
