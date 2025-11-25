# ======================================================
# 🧠 DAY 4: TEACH-THE-TUTOR (SQL EDITION)
# 👨‍💻 Tutorial by Akhil Ramola
# 🚀 Features: SELECT, Joins, Aggregation, Window Functions, CTE & Optimization
# ======================================================

import logging
import json
import os
import asyncio
from typing import Annotated, Literal, Optional
from dataclasses import dataclass

print("\n" + "📊" * 50)
print("🚀 SQL TUTOR - DAY 4 TUTORIAL")
print("💡 agent.py LOADED SUCCESSFULLY!")
print("📊" * 50 + "\n")

from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

# 🔌 PLUGINS
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# ======================================================
# 📚 KNOWLEDGE BASE (SQL DATA)
# ======================================================

CONTENT_FILE = "sql_content.json"

DEFAULT_CONTENT = [
    {
      "id": "select_where",
      "title": "SELECT & WHERE",
      "summary": "The SELECT statement is used to query data from a database. The WHERE clause allows filtering of rows based on conditions. " +
                 "In SQL, you should avoid `SELECT *` for performance reasons. Filters (WHERE) should be applied early to reduce the data scanned. " +
                 ":contentReference[oaicite:0]{index=0}",
      "sample_question": "What is a SELECT statement? How is the WHERE clause used in SQL?"
    },
    {
      "id": "joins",
      "title": "SQL Joins",
      "summary": "Joins combine rows from two or more tables based on related columns (keys). Common types include INNER JOIN, LEFT JOIN, RIGHT JOIN, and FULL JOIN. " +
                 "Using the right type of join is essential depending on whether you want matching rows only (INNER) or all rows from one side (LEFT/RIGHT). " +
                 ":contentReference[oaicite:1]{index=1}",
      "sample_question": "Explain the differences between INNER, LEFT, RIGHT, and FULL JOIN in SQL."
    },
    {
      "id": "group_by_having",
      "title": "Aggregation, GROUP BY & HAVING",
      "summary": "GROUP BY is used to group rows that share the same values in specified columns for aggregation (like SUM, COUNT). " +
                 "HAVING is used to filter results *after* aggregation. You cannot use the WHERE clause to filter aggregated values. " +
                 ":contentReference[oaicite:2]{index=2}",
      "sample_question": "When would you use GROUP BY and HAVING in a query? Give an example."
    },
    {
      "id": "subqueries",
      "title": "Subqueries",
      "summary": "A subquery is a query nested inside another query (SELECT, FROM, or WHERE). " +
                 "A correlated subquery references the outer query, meaning it runs for each row of the parent query. " +
                 ":contentReference[oaicite:3]{index=3}",
      "sample_question": "What is a correlated subquery? Provide an example."
    },
    {
      "id": "window_functions",
      "title": "Window Functions",
      "summary": "Window functions perform calculations across a set of rows related to the current row without collapsing results. They use the `OVER` clause. " +
                 "Unlike aggregate functions, window functions return a value for each row (e.g. running total, ranking). " +
                 ":contentReference[oaicite:4]{index=4}",
      "sample_question": "How do window functions differ from aggregation functions? Explain with an example."
    },
    {
      "id": "ctes_recursive",
      "title": "Common Table Expressions (CTEs) / Recursive Queries",
      "summary": "A CTE is a temporary, named result set which you define using `WITH` and can be referenced in a query. Recursive CTEs let a CTE refer to itself, useful for hierarchical data. " +
                 ":contentReference[oaicite:5]{index=5}",
      "sample_question": "What is a recursive CTE in SQL? How would you use it for hierarchical data?"
    },
    {
      "id": "index_optimization",
      "title": "Indexing & Query Optimization",
      "summary": "Indexes are used to speed up data retrieval in databases. Proper indexes (e.g. on WHERE and JOIN columns) can greatly improve performance. " +
                 "Also, best practices: avoid `SELECT *`, filter early, analyze execution plans. " +
                 ":contentReference[oaicite:6]{index=6}",
      "sample_question": "Why are indexes important in SQL? What’s the difference between an index and a key?"
    },
    {
      "id": "normalization",
      "title": "Normalization & Database Design",
      "summary": "Normalization is the process of organizing data to reduce redundancy. Common normal forms: 1NF, 2NF, 3NF. Good design helps maintain data integrity and performance. " +
                 ":contentReference[oaicite:7]{index=7}",
      "sample_question": "Explain the first three normal forms (1NF, 2NF, 3NF) in database design."
    }
]

def load_content():
    try:
        path = os.path.join(os.path.dirname(__file__), CONTENT_FILE)
        if not os.path.exists(path):
            print(f"⚠️ {CONTENT_FILE} not found. Generating SQL data...")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONTENT, f, indent=4)
            print("✅ SQL content file created successfully.")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"⚠️ Error managing content file: {e}")
        return []

COURSE_CONTENT = load_content()

# ======================================================
# 🧠 STATE MANAGEMENT
# ======================================================

@dataclass
class TutorState:
    current_topic_id: Optional[str] = None
    current_topic_data: Optional[dict] = None
    mode: Literal["learn", "quiz", "teach_back"] = "learn"

    def set_topic(self, topic_id: str):
        topic = next((item for item in COURSE_CONTENT if item["id"] == topic_id), None)
        if topic:
            self.current_topic_id = topic_id
            self.current_topic_data = topic
            return True
        return False

@dataclass
class Userdata:
    tutor_state: TutorState
    agent_session: Optional[AgentSession] = None

# ======================================================
# 🛠️ TUTOR TOOLS
# ======================================================

@function_tool
async def select_topic(
    ctx: RunContext[Userdata],
    topic_id: Annotated[str, Field(description="The ID of the SQL topic to study (e.g., 'joins', 'window_functions')")]
) -> str:
    state = ctx.userdata.tutor_state
    success = state.set_topic(topic_id.lower())

    if success:
        return f"Topic set to **{state.current_topic_data['title']}**. Do you want to 'Learn', be 'Quizzed', or 'Teach it back'?"
    else:
        available = ", ".join([t["id"] for t in COURSE_CONTENT])
        return f"Topic not found. Available topics are: {available}"

@function_tool
async def set_learning_mode(
    ctx: RunContext[Userdata],
    mode: Annotated[str, Field(description="The mode: 'learn', 'quiz', or 'teach_back'")]
) -> str:
    state = ctx.userdata.tutor_state
    mode_lower = mode.lower()
    if mode_lower not in ("learn", "quiz", "teach_back"):
        return "Invalid mode. Please choose 'learn', 'quiz', or 'teach_back'."

    state.mode = mode_lower
    agent_session = ctx.userdata.agent_session

    if agent_session:
        if state.mode == "learn":
            agent_session.tts.update_options(voice="en-US-matthew", style="Promo")
            instruction = f"Mode: LEARN. Explain the concept: {state.current_topic_data['summary']}"
        elif state.mode == "quiz":
            agent_session.tts.update_options(voice="en-US-alicia", style="Conversational")
            instruction = f"Mode: QUIZ. Ask this question: {state.current_topic_data['sample_question']}"
        else:  # teach_back
            agent_session.tts.update_options(voice="en-US-ken", style="Promo")
            instruction = "Mode: TEACH_BACK. Ask me to explain the concept to you as if you're a beginner."

    else:
        instruction = "Could not set voice (session not found)."

    print(f"🔄 SWITCHING MODE -> {state.mode.upper()}")
    return f"Switched to **{state.mode}** mode. {instruction}"

@function_tool
async def evaluate_teaching(
    ctx: RunContext[Userdata],
    user_explanation: Annotated[str, Field(description="The explanation given by the user during teach-back")]
) -> str:
    # You can improve this by calling an LLM to check correctness
    print(f"📝 EVALUATING EXPLANATION: {user_explanation}")
    # naive feedback
    return ("Thank you for your explanation. Here's my feedback:\n"
            "- **Accuracy**: 7/10 — you covered many key points.\n"
            "- **Clarity**: 8/10 — your explanation was clear.\n"
            "Some corrections / improvements:\n"
            f"  • The concept of *{ctx.userdata.tutor_state.current_topic_data['title']}* also involves … (add more depth based on the topic).\n"
            "Would you like to go over any part again?")

# ======================================================
# 🧠 AGENT DEFINITION
# ======================================================

class SQLEngineAgent(Agent):
    def __init__(self):
        topic_list = ", ".join([f"{t['id']} ({t['title']})" for t in COURSE_CONTENT])
        super().__init__(
            instructions=f"""
            You are a **SQL Tutor** designed to help users master SQL concepts important for interviews and real-world use.
            
            📚 **AVAILABLE TOPICS:** {topic_list}
            
            🔄 **YOU HAVE 3 MODES:**
            1. **LEARN Mode (Voice: Matthew):** Explain the concept using the summary.
            2. **QUIZ Mode (Voice: Alicia):** Ask the sample question to test the user.
            3. **TEACH_BACK Mode (Voice: Ken):** You act like a student: ask the user to explain the concept back to you.
            
            ⚙️ **BEHAVIOR:**
            - Ask the user which topic they want to study.
            - Use the `select_topic` tool to set the topic.
            - When user asks to “learn”, “quiz”, or “teach back”, call `set_learning_mode`.
            - In teach-back mode, listen to their explanation and then call `evaluate_teaching` to give feedback.
            """,
            tools=[select_topic, set_learning_mode, evaluate_teaching],
        )

# ======================================================
# 🎬 ENTRYPOINT
# ======================================================

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    print("\n" + "📊" * 25)
    print("🚀 STARTING SQL TUTOR SESSION")
    print(f"📚 Loaded {len(COURSE_CONTENT)} topics from Knowledge Base")

    userdata = Userdata(tutor_state=TutorState())
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Promo",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    userdata.agent_session = session

    await session.start(
        agent=SQLEngineAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
