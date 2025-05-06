import streamlit as st
import time
import random
import qrcode
from io import BytesIO
import base64

st.set_page_config(layout="wide")

# 1) Ask for the code once
if "role" not in st.session_state:
    st.title("🔐 Enter Quiz Code")
    code = st.text_input("Password or game PIN", type="password")
    if st.button("Join"):
        if code == st.secrets["host_password"]:
            st.session_state.role = "host"
            st.rerun()
        elif code == st.secrets["game_pin"]:
            st.session_state.role = "player"
            st.rerun()
        else:
            st.error("❌ Invalid code.")
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

    params = st.query_params               # new property-based API
    if params.get("start_quiz") == ["1"]:
        st.session_state.quiz_started = True
        # clear the param so a refresh won’t re-start
        st.set_query_params()              
        st.rerun()
        
    # ─── Initialize quiz_started flag ─────────────────────────────
    if "quiz_started" not in st.session_state:
        st.session_state.quiz_started = False

    # ─── Waiting Room Screen ──────────────────────────────────────
    if not st.session_state.get("quiz_started", False):
        # build the QR PNG as before…
        url = "https://peds-clerkship-shelf-reflection.streamlit.app/"
        qr = qrcode.make(url)
        buf = BytesIO(); qr.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
    
        st.markdown(
            f"""
            <style>
              /* center the entire waiting container */
              .waiting-room {{ text-align: center; padding: 2rem; }}
              /* style & center the “Start Quiz” link as a button */
              .waiting-room .start-btn {{
                display: inline-block;
                margin-top: 1.5rem;
                background-color: #f63366;
                color: white;
                padding: 0.75em 1.5em;
                font-size: 1.2rem;
                border-radius: 8px;
                text-decoration: none;
              }}
              .waiting-room .start-btn:hover {{
                background-color: #e52a58;
              }}
            </style>
    
            <div class="waiting-room">
              <h1>🕒 Waiting for students to join...</h1>
              <h2>🔢 Entry Code: <code style="font-size:1.2rem;">1234</code></h2>
              <p>Ask students to visit this page and enter the code to join.</p>
              <img src="data:image/png;base64,{b64}" width="200" />
              <br>
              <a href="?start_quiz=1" class="start-btn">🚀 Start Quiz</a>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Auto-refresh so the list updates without manual reload
        st_autorefresh(interval=2000, key="host_wait_refresh")
    
        st.markdown("### 👥 Participants Joined")
    
        # Fetch & order by join time
        docs = db.collection("participants") \
                 .order_by("timestamp") \
                 .stream()
    
        rows = []
        for i, d in enumerate(docs, start=1):
            p = d.to_dict()
            rows.append({"#": i, "Nickname": p["nickname"]})
        
        if rows:
            # Build an HTML badge for each participant
            badges = "".join([
                f"<span style='\
                    display:inline-block;\
                    background:#E3F2FD;\
                    color:#333;\
                    padding:8px 16px;\
                    margin:4px;\
                    border-radius:12px;\
                    font-size:1rem;\
                    font-weight:500;\
                    box-shadow:0 2px 4px rgba(0,0,0,0.1);\
                '>{r['#']}. {r['Nickname']}</span>"
                for r in rows
            ])
        
            # Wrap in a centered container
            st.markdown(
                f"""
                <div style="text-align:center; margin-top:1rem; margin-bottom:1rem;">
                  <h3 style="margin-bottom:0.5rem;">👥 Participants Joined ({len(rows)})</h3>
                  {badges}
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                "<p style='text-align:center; font-style:italic; color:#666;'>No one has joined yet.</p>",
                unsafe_allow_html=True
            )
            
        st.stop()
        
    # ─── Auto-refresh during quiz ─────────────────────────────────
    st_autorefresh(interval=2000, key="host_refresh")

    # ─── Load questions & index ───────────────────────────────────
    questions = load_questions()
    total_q = len(questions)
    if "host_idx" not in st.session_state:
        st.session_state.host_idx = get_current_index()
    idx = st.session_state.host_idx

    # ─── Show current question ────────────────────────────────────
    st.markdown(f"### Question {idx+1} / {total_q}")
    q = questions[idx]
    st.write(q["text"])
    if q["type"] == "mc":
        for opt in q["options"]:
            st.write(f"- {opt}")

    # ─── Advance button ───────────────────────────────────────────
    if st.button("➡️ Next Question"):
        new_idx = (idx + 1) % total_q
        st.session_state.host_idx = new_idx
        set_current_index(new_idx)
        st.rerun()

    # ─── Student Responses ────────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 Student Answers")

    resp_docs = (
        db.collection("responses")
          .where("question_id", "==", idx)
          .stream()
    )
    answers = [doc.to_dict().get("answer", "") for doc in resp_docs]

    if answers:
        random.shuffle(answers)
        bg_colors = ["#E3F2FD", "#FCE4EC", "#E8F5E9", "#FFF3E0", "#F3E5F5"]
        for i, a in enumerate(answers):
            color = bg_colors[i % len(bg_colors)]
            st.markdown(
                f"""
                <div style="
                    background-color: {color};
                    padding: 16px;
                    margin: 10px 0;
                    border-radius: 10px;
                    text-align: center;
                    font-size: 1.4rem;
                    font-weight: bold;
                    transition: all 0.3s ease;
                "
                onmouseover="this.style.transform='scale(1.03)'"
                onmouseout="this.style.transform='scale(1)'"
                >
                    {a}
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.write("No responses submitted yet.")

from streamlit_autorefresh import st_autorefresh

# ─── Player View ───────────────────────────────────────────────────────────
if st.session_state.role == "player":
    st.title("🕹️ Quiz Player")
    nick = st.text_input("Enter your nickname", key="nick")
    if not nick:
        st.info("Please choose a nickname to join the game.")
        st.stop()
    if not st.session_state.get("joined", False):
        # write a participant record once per session
        db.collection("participants").add({
            "nickname":  nick,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        st.session_state.joined = True
    
    # ←–– Auto-refresh every 2s
    st_autorefresh(interval=2000, key="player_refresh")

    # 1) Fetch host’s index and “lock it in” as active_idx
    fs_idx = get_current_index()
    if ("active_idx" not in st.session_state) or (st.session_state.active_idx != fs_idx):
        st.session_state.active_idx = fs_idx
        # clear any old submitted flag for this question
        st.session_state.pop(f"submitted_{fs_idx}", None)

    current_idx = st.session_state.active_idx

    # 2) Load the question
    q_doc = db.collection("questions").document(str(current_idx)).get()
    if not q_doc.exists:
        st.error(f"No question found for index {current_idx}")
        st.stop()
    q = q_doc.to_dict()

    # 3) Single submitted flag
    submitted_key = f"submitted_{current_idx}"

    # 4) Show the form if not yet submitted
    if not st.session_state.get(submitted_key, False):
        with st.form(key=f"form_{current_idx}"):
            st.markdown(f"### Q{current_idx+1}. {q['text']}")
            if q["type"] == "mc":
                choice = st.radio("Choose one:", q["options"], key=f"mc_{current_idx}")
            else:
                choice = st.text_input("Your answer:", key=f"text_{current_idx}")
            clicked = st.form_submit_button("Submit Answer")

        if clicked:
            # write once
            db.collection("responses").add({
                "question_id": current_idx,
                "nickname":    nick,
                "answer":      choice,
                "timestamp":   firestore.SERVER_TIMESTAMP
            })
            # mark as submitted and show confirmation
            st.session_state[submitted_key] = True
            st.success("✅ Answer submitted!")

    # 5) If already submitted, show this
    else:
        st.success("✅ Please look up at the screen")


