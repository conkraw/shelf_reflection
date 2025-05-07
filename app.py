import streamlit as st
import time
import random
import qrcode
from io import BytesIO
import base64
import os
import requests

st.set_page_config(layout="wide")

def display_repo_image(image_field: str):
    """
    Given an image_field like "test" or "diagram.jpg",
    tries a variety of extensions (including uppercase) and
    renders the first one that actually exists on GitHub.
    """
    base = "https://raw.githubusercontent.com/conkraw/shelf_reflection/main/"
    name = image_field.strip()

    # Build candidate filenames
    if os.path.splitext(name)[1]:
        candidates = [name]
    else:
        exts = [".png", ".PNG", ".jpg", ".JPG", ".jpeg", ".JPEG", ".gif", ".GIF"]
        candidates = [name + ext for ext in exts]

    for fn in candidates:
        url = base + fn
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                # we got it! render from bytes
                #st.image(BytesIO(r.content), use_container_width=True)
                st.image(BytesIO(r.content))
                return
        except requests.RequestException:
            pass

    # nothing worked
    st.warning(f"Could not find image `{image_field}` (tried {', '.join(candidates)})")

st.markdown("""
<style>
/* Center all Streamlit buttons */
div.stButton > button {
  margin: 0 auto;
  display: block;
}
</style>
""", unsafe_allow_html=True)

# 1) Ask for the code once
if "role" not in st.session_state:
    st.title("🔐 Enter Quiz Code")
    code = st.text_input("Password or game PIN", type="password")
    if st.button("Join"):
        if code == st.secrets["host_password"]:
            st.session_state.role = "host"
            st.session_state.quiz_id = st.secrets["quiz_id"]  # ✅ use actual quiz ID
            st.rerun()
        elif code == st.secrets["game_pin"]:
            st.session_state.role = "player"
            st.session_state.quiz_id = st.secrets["quiz_id"]  # ✅ same quiz ID for player
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
    try:
        quiz_id = st.session_state.quiz_id
        docs = db.collection(quiz_id).order_by("__name__").stream()
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
    db.document("game_state/current").set(
        {"current_index": idx},
        merge=True           # <-- preserves any other keys, like "started"
    )

# ─── 2. App Configuration ─────────────────────────────────────────────────────
if st.session_state.role == "host":
    #st.title("🔧 Quiz Host Controller")
    if st.button("🗑️ Reset Game Data"):
        # 1) Delete participants
        for doc in db.collection("participants").stream():
            doc.reference.delete()
        # 2) Delete responses
        for doc in db.collection("responses").stream():
            doc.reference.delete()
        # 3) Delete the current game_state doc
        db.document("game_state/current").delete()
        
        st.success("✅ All game data has been reset.")
        st.rerun()
      

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
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Auto-refresh so the list updates without manual reload
        st_autorefresh(interval=2000, key="host_wait_refresh")
    
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

         # This button will now be perfectly centered:
        if st.button("🚀 Start Quiz"):
            # Mark in Firestore that the quiz has started
            db.document("game_state/current").set(
                {"started": True}, merge=True
            )
            st.session_state.quiz_started = True
            st.rerun()
        st.stop()  # don’t proceed until they click

# ─── RESULTS SCREEN ────────────────────────────────────────────────
    if st.session_state.get("show_results", False):
        st.markdown("<h2 style='text-align: center;'>🏆 Final Quiz Results</h2>",unsafe_allow_html=True)

        # 1) Build stats: count correct MC answers & avg speed
        participants = {}
        all_resps   = db.collection("responses").stream()
        questions   = load_questions()
        for d in all_resps:
            r    = d.to_dict()
            qid  = r["question_id"]
            q    = questions[qid]
            # only MC corrects count
            if q["type"] == "mc" and r["answer"] == q.get("ans"):
                nick = r["nickname"]
                ts   = r["timestamp"]
                dt   = ts.ToDatetime() if hasattr(ts, "ToDatetime") else ts
                sec  = dt.timestamp()
                p    = participants.setdefault(nick, {"count":0, "times":[]})
                p["count"]  += 1
                p["times"].append(sec)

        # 2) Prepare leaderboard
        board = []
        for nick, data in participants.items():
            avg_time = sum(data["times"])/len(data["times"])
            board.append((nick, data["count"], avg_time))
        # sort by count desc, then avg_time asc
        board.sort(key=lambda x:(-x[1], x[2]))

        # 3) Show top 3
        if board:
            places = ["🍬", "🍩", "🍭"]
            for i, entry in enumerate(board[:3]):
                nick, cnt, _ = entry
                st.header(f"{places[i]} **{nick}** — {cnt} correct")
            # and list anyone else
            if len(board) > 3:
                st.header("**Others:** " + ", ".join(n for n,_,_ in board[3:]))
        else:
            st.write("No correct answers were submitted.")

        st.stop()
      
    # ─── Auto-refresh during quiz ─────────────────────────────────
    st_autorefresh(interval=2000, key="host_refresh")

    # ─── Load questions & index ───────────────────────────────────
    questions = load_questions()
    total_q = len(questions)
    if "host_idx" not in st.session_state:
        st.session_state.host_idx = get_current_index()
    idx = st.session_state.host_idx

    # ensure we have a show_answer flag
    if "show_answer" not in st.session_state:
        st.session_state.show_answer = False
    
    q = questions[idx]

    if not st.session_state.show_answer:
        # 1) Show question
        st.markdown(f"### Question {idx+1} / {total_q}")
        st.write(q["text"])
        if q.get("image"):
            display_repo_image(q["image"])

        if q["type"] == "mc":
            for opt in q["options"]:
                st.write(f"- {opt}")
    
        # 2) Button to reveal answer
        if st.button("Show Answer"):
            st.session_state.show_answer = True
            st.rerun()
    
    else:
        # 3) Show the correct answer
        correct = q.get("ans", "")
        st.success(f"💡 Correct Answer: **{correct}**")
    
        # 4) If multiple‐choice, find first correct responder
        if q["type"] == "mc":
            # fetch all responses for this question
            resp_docs = db.collection("responses") \
                          .where("question_id", "==", idx) \
                          .stream()
            correct_resps = []
            for d in resp_docs:
                r = d.to_dict()
                if r.get("answer") == correct:
                    ts = r.get("timestamp")
                    # convert Firestore ts to datetime if needed
                    dt = ts.ToDatetime() if hasattr(ts, "ToDatetime") else ts
                    correct_resps.append((r.get("nickname"), dt))
            if correct_resps:
                # pick the earliest
                correct_resps.sort(key=lambda x: x[1])
                first_nick = correct_resps[0][0]
                st.info(f"🏆 First correct responder: **{first_nick}**")
            else:
                st.info("No one has answered correctly yet.")
    
        # 5) Next Question button
        if st.button("➡️ Next Question", key=f"next_btn_{idx}"):
            new_idx = (idx + 1) % total_q
            st.session_state.host_idx    = new_idx
            st.session_state.show_answer = False
            set_current_index(new_idx)
            st.rerun()

        if st.session_state.show_answer and idx == total_q - 1:
          if st.button("🏁 Show Results", key="show_results_btn"):
              st.session_state.show_results = True
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

    # ─── 1) Nickname & join logic ────────────────────────────────────
    if not st.session_state.get("joined", False):
        nick = st.text_input("Pick a fun nickname to play (avoid using real names)", key="nick_input")
        if st.button("Join Game"):
            if not nick.strip():
                st.error("Please enter a valid nickname.")
            else:
                db.collection("participants").add({
                    "nickname":  nick,
                    "timestamp": firestore.SERVER_TIMESTAMP
                })
                st.session_state.nick   = nick
                st.session_state.joined = True
                st.rerun()
        st.stop()  # nothing else until they join

    # Greet them once joined
    nick = st.session_state.nick
    st.markdown(f"**👋 Hello, {nick}!**")

    st_autorefresh(interval=2000, key="waiting_for_host")
    
    # ─── WAIT FOR HOST ────────────────────────────────
    status = db.document("game_state/current").get().to_dict() or {}
    if not status.get("started", False):
        st.warning("⏳ Waiting for the host to start the quiz…")
        
        st.markdown("""
        ---
        ### ℹ️ Instructions for Participants
        
        - ⏱️ **There is no timer.** The question ends when the host reveals the answer.
        - 💡 **These questions are meant to enhance your learning** and support your growth as future physicians.
        - 🔍 While we’ve carefully reviewed all content, **some questions may still have errors.** Please feel free to reach out if you notice anything that seems incorrect.
        - 📚 We encourage you to **use your own clinical reasoning and trusted resources** to reflect on each question.
        - 🏅 **Top scorers are displayed at the end** — not to compete, but to recognize engagement and effort!
        - 🤝 This is a **low-stakes, supportive environment** — your participation is what matters most.
        
        ---
        """)

        st.stop()

    # 1) Fetch host’s index and “lock it in” as active_idx
    fs_idx = get_current_index()
    if ("active_idx" not in st.session_state) or (st.session_state.active_idx != fs_idx):
        st.session_state.active_idx = fs_idx
        # clear any old submitted flag for this question
        st.session_state.pop(f"submitted_{fs_idx}", None)

    current_idx = st.session_state.active_idx

    # 2) Load the question
    quiz_id = st.session_state.quiz_id
    q_doc = db.collection(quiz_id).document(str(current_idx)).get()
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
            if q.get("image"):
                display_repo_image(q["image"])
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
            st.rerun()

    # 5) If already submitted, show this
    else:
        st.success("✅ Please look up at the screen")
        st_autorefresh(interval=2000, key=f"refresh_after_{current_idx}")


