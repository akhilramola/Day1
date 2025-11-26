# ======================================================
# 💼 AI SALES DEVELOPMENT REP (SDR) for Physics Wallah (PW)
# 🚀 Features: FAQ Retrieval, Lead Qualification, JSON Lead Store
# ======================================================

import logging
import json
import os
import asyncio
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

print("\n" + "💼" * 30)
print("🚀 AI SDR AGENT — Physics Wallah (PW)")
print("📚 Selling: PW online/offline courses (school, JEE/NEET, test-series etc.)")
print("💡 agent.py LOADED SUCCESSFULLY!")
print("💼" * 30 + "\n")

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

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# ======================================================
# 📂 1. KNOWLEDGE BASE (FAQ for PW)
# ======================================================

FAQ_FILE = "pw_faq.json"
LEADS_FILE = "pw_leads_db.json"

DEFAULT_PW_FAQ = [
    {
        "question": "What is Physics Wallah?",
        "answer": "Physics Wallah (PW) is an Indian ed-tech platform offering affordable online and offline education for students in classes 6-12, and aspirants preparing for exams like JEE and NEET. They provide video lectures, live classes, test series, NCERT solutions and study resources. :contentReference[oaicite:1]{index=1}"
    },
    {
        "question": "Who founded Physics Wallah and when?",
        "answer": "PW was started by Alakh Pandey as a YouTube channel in 2016, and later co-founded with Prateek Maheshwari when the official app/company launched. :contentReference[oaicite:2]{index=2}"
    },
    {
        "question": "What courses / exams do you cover?",
        "answer": "We cover school classes (6 to 12), board curricula and competitive exam preparation like JEE and NEET. PW provides online video lectures, live classes, test series, and study materials. :contentReference[oaicite:3]{index=3}"
    },
    {
        "question": "Do you offer offline or hybrid classes?",
        "answer": "Yes — apart from online courses, PW operates offline / hybrid coaching centres across India in many locations. :contentReference[oaicite:4]{index=4}"
    },
    {
        "question": "Do you provide free lectures / content?",
        "answer": "Yes. Physics Wallah originally started as a YouTube channel, and many lectures remain free on YouTube and perhaps on the PW platform. :contentReference[oaicite:5]{index=5}"
    },
    {
        "question": "What is the cost / pricing of courses?",
        "answer": "PW aims to keep education affordable; earlier reporting noted modest tuition fees when the app launched. Exact pricing varies depending on course type (online / offline / test-series / batch). :contentReference[oaicite:6]{index=6}"
    }
    # — you can add more entries as needed.
]

def load_knowledge_base():
    try:
        path = os.path.join(os.path.dirname(__file__), FAQ_FILE)
        if not os.path.exists(path):
            with open(path, "w", encoding='utf-8') as f:
                json.dump(DEFAULT_PW_FAQ, f, indent=4)
        with open(path, "r", encoding='utf-8') as f:
            return json.dumps(json.load(f))
    except Exception as e:
        print(f"⚠️ Error loading FAQ: {e}")
        return ""

PW_FAQ_TEXT = load_knowledge_base()

# ======================================================
# 💾 2. LEAD DATA STRUCTURE
# ======================================================

@dataclass
class LeadProfile:
    name: Optional[str] = None
    user_type: Optional[str] = None  # student / parent / coaching-institute / working professional
    email: Optional[str] = None
    target_exam_or_grade: Optional[str] = None  # e.g. JEE, NEET, class 12 CBSE
    use_case: Optional[str] = None  # What they want: school board, entrance prep, etc.
    timeline: Optional[str] = None  # When they plan to start: now / next month / next academic year

    def is_qualified(self):
        return all([self.name, self.email, self.use_case])

@dataclass
class Userdata:
    lead_profile: LeadProfile

# ======================================================
# 🛠️ 3. SDR TOOLS
# ======================================================

@function_tool
async def update_lead_profile(
    ctx: RunContext[Userdata],
    name: Optional[str] = None,
    user_type: Optional[str] = None,
    email: Optional[str] = None,
    target_exam_or_grade: Optional[str] = None,
    use_case: Optional[str] = None,
    timeline: Optional[str] = None,
) -> str:
    profile = ctx.userdata.lead_profile
    if name: profile.name = name
    if user_type: profile.user_type = user_type
    if email: profile.email = email
    if target_exam_or_grade: profile.target_exam_or_grade = target_exam_or_grade
    if use_case: profile.use_case = use_case
    if timeline: profile.timeline = timeline
    print(f"📝 UPDATING LEAD: {profile}")
    return "Lead profile updated. Continue the conversation."

@function_tool
async def submit_lead_and_end(
    ctx: RunContext[Userdata],
) -> str:
    profile = ctx.userdata.lead_profile
    db_path = os.path.join(os.path.dirname(__file__), LEADS_FILE)
    entry = asdict(profile)
    entry["timestamp"] = datetime.now().isoformat()
    existing_data = []
    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                existing_data = json.load(f)
        except: pass
    existing_data.append(entry)
    with open(db_path, "w") as f:
        json.dump(existing_data, f, indent=4)
    print(f"✅ LEAD SAVED TO {LEADS_FILE}")
    return f"Lead saved. Thanks {profile.name}! We’ve recorded that you want: {profile.use_case} (Target: {profile.target_exam_or_grade}), timeline: {profile.timeline}. We’ll email you at {profile.email} with next steps. Good bye!"

# ======================================================
# 🧠 4. AGENT DEFINITION
# ======================================================

class SDRAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=f"""
            You are 'Ananya', a friendly and professional Sales Development Rep (SDR) for Physics Wallah (PW).

            📘 YOUR KNOWLEDGE BASE (FAQ + company info):
            {PW_FAQ_TEXT}

            🎯 YOUR GOAL:
            1. Answer questions about PW’s offerings (online/offline courses, test-series, exam prep) using only the info provided above.
            2. QUALIFY THE LEAD: Naturally ask for:
               - Name
               - Are you a student / parent / coaching-institute / working professional?
               - Email or contact
               - What you're aiming for (grade / exam)
               - What you want: board-class, JEE/NEET prep, etc. (Use Case)
               - When you plan to start (Timeline)

            ⚙️ BEHAVIOR:
            - After answering a question, gently ask a lead-qualification question.
              Example: “Sure — we cover JEE. By the way, may I know which exam you’re preparing for?”
            - Don’t push — let user volunteer info.
            - If user asks something not in the FAQ (e.g. exact batch start date), reply: “I’m not sure, I’ll check and get back to you soon.”
            - Use update_lead_profile when user gives info.
            - When user says “That’s all”, “Thanks”, etc., call submit_lead_and_end.

            🚫 RESTRICTIONS:
            - Do not invent batch-dates, fees, or syllabus details if not in FAQ.
            """
            ,
            tools=[update_lead_profile, submit_lead_and_end],
        )

# ======================================================
# 🎬 ENTRYPOINT
# ======================================================

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    userdata = Userdata(lead_profile=LeadProfile())

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-natalie",
            style="Promo",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    await session.start(
        agent=SDRAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
