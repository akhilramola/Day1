"""
Day 8 – Voice Game Master (D&D-Style Adventure) - Voice-only GM agent

- Uses LiveKit agent plumbing similar to the provided food_agent_sqlite example.
- GM persona, universe, tone and rules are encoded in the agent instructions.
- Keeps STT/TTS/Turn detector/VAD integration untouched (murf, deepgram, silero, turn_detector).
- Tools:
    - start_adventure(): start a fresh session and introduce the scene
    - get_scene(): return the current scene description (GM text) ending with "What do you do?"
    - player_action(action_text): accept player's spoken action, update state, advance scene
    - show_journal(): list remembered facts, NPCs, named locations, choices
    - restart_adventure(): reset state and start over
- Userdata keeps continuity between turns: history, inventory, named NPCs/locations, choices, current_scene
"""

import json
import logging
import os
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Annotated

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

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("voice_game_master")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

load_dotenv(".env.local")

# -------------------------
# Simple Game World Definition – Eldoria Baby Dragon Quest
# -------------------------
# A compact Eldoria world with a few scenes and choices forming a mini-arc.
WORLD = {
    "intro": {
        "title": "Bells of Eldoria",
        "desc": (
            "The town bells ring wildly in the sleepy Kingdom of Eldoria. A royal crier shouts the decree:\n"
            "\"A baby dragon has gone missing! Whoever returns it shall be named Hero of Eldoria… and granted unlimited bakery pastries!\"\n\n"
            "You stand by the cobblestone gate. To your left, the bustling market square; ahead, a forest path glowing faintly with tiny clawed footprints; "
            "to the right, the royal courtyard where the Queen’s steward paces nervously."
        ),
        "choices": {
            "go_market": {
                "desc": "Head to the market square to gather rumors.",
                "result_scene": "market",
            },
            "follow_tracks": {
                "desc": "Follow the faint glowing claw-prints toward the forest.",
                "result_scene": "forest_edge",
            },
            "go_courtyard": {
                "desc": "Go to the royal courtyard and speak with the steward.",
                "result_scene": "courtyard",
            },
        },
    },
    "market": {
        "title": "The Market of Voices",
        "desc": (
            "The market smells of fresh bread and metalwork. A baker waves a flour-dusted hand, and a grinning stable-hand whispers:\n"
            "\"That baby dragon loves sweet rolls and warm milk. If you had treats, it might trust you.\"\n"
            "A tray of spare sweet rolls sits unattended near the stall."
        ),
        "choices": {
            "take_treats": {
                "desc": "Take a few sweet rolls as dragon treats.",
                "result_scene": "market_after_treats",
                "effects": {"add_inventory": "dragon_treats", "add_journal": "You picked up sweet rolls for the baby dragon."},
            },
            "ask_rumors": {
                "desc": "Ask around for rumors of where the dragon went.",
                "result_scene": "market_rumors",
                "effects": {"add_journal": "Heard that glowing tracks lead into the Whispering Forest."},
            },
            "return_gate": {
                "desc": "Return to the city gate.",
                "result_scene": "intro",
            },
        },
    },
    "market_after_treats": {
        "title": "Loaded with Pastries",
        "desc": (
            "You tuck the sweet rolls into your pack. The baker pretends not to see but smiles anyway.\n"
            "The stable-hand nudges you: \"Follow the glow into the forest. Just… be kind, yeah?\""
        ),
        "choices": {
            "follow_tracks": {
                "desc": "Head out and follow the glowing prints toward the forest.",
                "result_scene": "forest_edge",
            },
            "return_gate": {
                "desc": "Return to the city gate first.",
                "result_scene": "intro",
            },
        },
    },
    "market_rumors": {
        "title": "Rumors and Whispers",
        "desc": (
            "Merchants talk over each other: dragons nesting near the old hill cave, mysterious humming in the forest, and a wizard who once watched over dragon eggs.\n"
            "Everyone agrees: the glowing claw-prints lead into the Whispering Forest."
        ),
        "choices": {
            "follow_tracks": {
                "desc": "Leave the market and follow the glowing prints to the forest.",
                "result_scene": "forest_edge",
            },
            "take_treats": {
                "desc": "Grab some sweet rolls before you go.",
                "result_scene": "market_after_treats",
                "effects": {"add_inventory": "dragon_treats", "add_journal": "You grabbed sweet rolls after hearing the rumors."},
            },
            "return_gate": {
                "desc": "Head back to the gate.",
                "result_scene": "intro",
            },
        },
    },
    "courtyard": {
        "title": "Royal Courtyard",
        "desc": (
            "Marble arches frame a nervous steward pacing. When you approach, they whisper:\n"
            "\"The Queen’s heart is broken. That dragon was meant to guard the city one day. "
            "It’s just a hatchling—easily frightened but soothed by kindness and sweets.\"\n"
            "They press a small cloth bundle into your hands."
        ),
        "choices": {
            "open_bundle": {
                "desc": "Open the bundle and see what’s inside.",
                "result_scene": "courtyard_gift",
                "effects": {"add_inventory": "royal_treats", "add_journal": "Received royal-approved dragon treats from the steward."},
            },
            "ask_details": {
                "desc": "Ask for more details about the dragon.",
                "result_scene": "courtyard_details",
                "effects": {"add_journal": "Learned the dragon is curious but hates loud shouting."},
            },
            "return_gate": {
                "desc": "Return to the gate.",
                "result_scene": "intro",
            },
        },
    },
    "courtyard_gift": {
        "title": "Royal Gift",
        "desc": (
            "Inside the bundle are carefully wrapped sweet rolls and a tiny silver charm shaped like a dragon’s claw.\n"
            "The steward says, \"If you return the hatchling, the Queen will reward you beyond pastries. But please, keep it safe.\""
        ),
        "choices": {
            "follow_tracks": {
                "desc": "Leave through the gate and follow the glowing tracks to the forest.",
                "result_scene": "forest_edge",
            },
            "return_gate": {
                "desc": "Head back to the city gate to plan.",
                "result_scene": "intro",
            },
        },
    },
    "courtyard_details": {
        "title": "Dragon Lore",
        "desc": (
            "The steward explains: \"The hatchling sings softly when calm and hiccups sparks when afraid. "
            "It probably hid somewhere dim and cozy—maybe the old hill cave past the forest.\""
        ),
        "choices": {
            "follow_tracks": {
                "desc": "Set off toward the forest, following the glowing prints.",
                "result_scene": "forest_edge",
            },
            "return_gate": {
                "desc": "Return to the gate to think.",
                "result_scene": "intro",
            },
        },
    },
    "forest_edge": {
        "title": "Edge of the Whispering Forest",
        "desc": (
            "Trees crowd together, their leaves whispering secrets. The glowing claw-prints lead inward along a winding path. "
            "Sometimes you hear a tiny, musical hiccup deeper within."
        ),
        "choices": {
            "follow_glow": {
                "desc": "Follow the glowing prints deeper into the forest.",
                "result_scene": "forest_path",
            },
            "call_softly": {
                "desc": "Call softly for the dragon, trying not to scare it.",
                "result_scene": "forest_call",
            },
            "retreat_city": {
                "desc": "Lose your nerve and retreat back to the city gate.",
                "result_scene": "intro",
            },
        },
    },
    "forest_call": {
        "title": "A Soft Call",
        "desc": (
            "You call out gently. For a moment, the forest holds its breath. Then you hear a tiny, startled chirp and a puff of sparks in the distance.\n"
            "The claw-prints brighten, pointing the way like fireflies under your feet."
        ),
        "choices": {
            "follow_glow": {
                "desc": "Follow the brightened prints toward the sound.",
                "result_scene": "forest_path",
            },
            "wait_listen": {
                "desc": "Wait and listen to see if the dragon comes closer.",
                "result_scene": "forest_listen",
            },
        },
    },
    "forest_listen": {
        "title": "Listening in the Dark",
        "desc": (
            "You stand very still. Leaves rustle. A curious chirring sound circles you, then fades toward the old hill path.\n"
            "The prints drift that way, clearer than before."
        ),
        "choices": {
            "follow_glow": {
                "desc": "Follow the prints up the hill path.",
                "result_scene": "cave_entrance",
            },
        },
    },
    "forest_path": {
        "title": "Winding Path",
        "desc": (
            "The forest thickens, but the glowing prints lead you up a rising trail. "
            "You smell faint smoke and something like… burnt sugar.\n"
            "Ahead, a rocky hill with a cave mouth yawns in the twilight."
        ),
        "choices": {
            "go_cave": {
                "desc": "Head straight to the cave entrance.",
                "result_scene": "cave_entrance",
            },
            "call_softly": {
                "desc": "Call softly again before approaching.",
                "result_scene": "forest_call",
            },
        },
    },
    "cave_entrance": {
        "title": "Old Hill Cave",
        "desc": (
            "Warm air drifts from the cave. Inside, you hear a wavering hum and the occasional tiny hiccup followed by a sprinkle of sparks.\n"
            "The ground near the entrance is scattered with half-melted pebbles and a few burnt pastry crumbs."
        ),
        "choices": {
            "enter_carefully": {
                "desc": "Enter carefully, speaking in a calm, kind voice.",
                "result_scene": "dragon_nest",
                "effects": {"add_journal": "You approached the dragon’s hiding place gently."},
            },
            "offer_treats": {
                "desc": "Sit at the entrance and place some treats where the dragon can see them.",
                "result_scene": "dragon_lured",
                "effects": {"add_journal": "You tried to lure the dragon with sweets."},
            },
            "shout_inside": {
                "desc": "Shout into the cave demanding the dragon come out.",
                "result_scene": "dragon_scared",
                "effects": {"add_journal": "You startled the hatchling with loud shouting."},
            },
        },
    },
    "dragon_scared": {
        "title": "Sparks and Scrambling",
        "desc": (
            "Your shout echoes like thunder. Inside, a frightened squeal erupts, followed by a burst of sparks. "
            "You hear scrambling as the hatchling retreats deeper into the cave.\n"
            "The glow of the prints dims, as if offended."
        ),
        "choices": {
            "apologize": {
                "desc": "Softly apologize and step back from the entrance.",
                "result_scene": "dragon_lured",
                "effects": {"add_journal": "You apologized after scaring the dragon."},
            },
            "leave": {
                "desc": "Give up and leave the cave behind.",
                "result_scene": "forest_edge",
            },
        },
    },
    "dragon_lured": {
        "title": "Tempting with Sweets",
        "desc": (
            "You set out the treats and wait. Slowly, a small, shimmering snout pokes from the darkness. "
            "A baby dragon with pearl-green scales sniffs, then cautiously hops forward, hiccupping tiny sparks.\n"
            "It eyes you curiously."
        ),
        "choices": {
            "speak_gently": {
                "desc": "Speak gently and promise to take it somewhere safe with more pastries.",
                "result_scene": "dragon_trust",
                "effects": {"add_journal": 'The dragon began to trust your voice.'},
            },
            "rush_forward": {
                "desc": "Grab for the dragon quickly before it can flee.",
                "result_scene": "dragon_startled",
                "effects": {"add_journal": "You lunged at the dragon, startling it."},
            },
        },
    },
    "dragon_nest": {
        "title": "Inside the Nest",
        "desc": (
            "Inside the cave, you see a makeshift nest of blankets and old banners. "
            "The baby dragon sits in the center, humming sadly, a half-burnt pastry clutched in its claws.\n"
            "Its eyes widen when it sees you, unsure whether to flee or sing."
        ),
        "choices": {
            "show_treats": {
                "desc": "Show any treats you brought and kneel to appear smaller.",
                "result_scene": "dragon_trust",
                "effects": {"add_journal": "You knelt and showed the dragon you came with gifts."},
            },
            "sing_softly": {
                "desc": "Sing a soft, silly song to calm it.",
                "result_scene": "dragon_trust",
                "effects": {"add_journal": "You sang to the dragon until it calmed."},
            },
            "back_away": {
                "desc": "Back away and leave it be.",
                "result_scene": "forest_edge",
            },
        },
    },
    "dragon_startled": {
        "title": "Trust Broken",
        "desc": (
            "You lunge forward. The hatchling squeals and lets out a shower of sparks, scrambling back into the nest. "
            "It glares at you with hurt eyes, clutching its pastry tighter.\n"
            "This might be harder now."
        ),
        "choices": {
            "apologize": {
                "desc": "Apologize and move slowly, offering another treat.",
                "result_scene": "dragon_trust",
                "effects": {"add_journal": "You tried to fix your mistake and earn back its trust."},
            },
            "leave": {
                "desc": "Leave the cave, ashamed.",
                "result_scene": "forest_edge",
            },
        },
    },
    "dragon_trust": {
        "title": "A Tiny Friend",
        "desc": (
            "With patience and kindness, the baby dragon shuffles closer. It nudges your hand, then hops into your arms, "
            "curled like a warm, humming cat made of embers.\n"
            "It chirps once, as if saying: \"Home?\""
        ),
        "choices": {
            "return_city": {
                "desc": "Carry the dragon carefully back to Eldoria.",
                "result_scene": "city_return",
                "effects": {"add_journal": "You convinced the hatchling to return with you."},
            },
            "keep_exploring": {
                "desc": "Let it ride on your shoulder and explore the forest a bit longer.",
                "result_scene": "forest_edge",
                "effects": {"add_journal": "You and the dragon explored the forest together."},
            },
        },
    },
    "city_return": {
        "title": "Hero of Eldoria",
        "desc": (
            "You return through the gates of Eldoria with the baby dragon perched proudly on your shoulder. "
            "The crowd erupts in cheers. The Queen’s steward rushes forward, eyes shining with relief.\n"
            "The dragon chirps happily and promptly steals a sweet roll from your pack.\n\n"
            "Banners are raised. Your name is added to the rolls of Heroes of Eldoria, and the bakery vows that you shall never know a day without fresh pastries.\n\n"
            ">>> MINI-ARC COMPLETE. Type 'restart' if you want a new adventure with the hatchling in another mood."
        ),
        "choices": {
            "end_session": {
                "desc": "Bask in the applause and end this tale.",
                "result_scene": "intro",
            },
        },
    },
}

# -------------------------
# Per-session Userdata
# -------------------------
@dataclass
class Userdata:
    player_name: Optional[str] = None
    current_scene: str = "intro"
    history: List[Dict] = field(default_factory=list)  # list of {'scene', 'action', 'time', 'result_scene'}
    journal: List[str] = field(default_factory=list)
    inventory: List[str] = field(default_factory=list)
    named_npcs: Dict[str, str] = field(default_factory=dict)
    choices_made: List[str] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

# -------------------------
# Helper functions
# -------------------------
def scene_text(scene_key: str, userdata: Userdata) -> str:
    """
    Build the descriptive text for the current scene, and append choices as short hints.
    Always end with 'What do you do?' so the voice flow prompts player input.
    """
    scene = WORLD.get(scene_key)
    if not scene:
        return "You drift in a featureless void. What do you do?"

    desc = f"{scene['desc']}\n\nChoices:\n"
    for cid, cmeta in scene.get("choices", {}).items():
        desc += f"- {cmeta['desc']} (say: {cid})\n"
    # GM MUST end with the action prompt
    desc += "\nWhat do you do?"
    return desc

def apply_effects(effects: dict, userdata: Userdata):
    if not effects:
        return
    if "add_journal" in effects:
        userdata.journal.append(effects["add_journal"])
    if "add_inventory" in effects:
        userdata.inventory.append(effects["add_inventory"])
    # Extendable for more effect keys later

def summarize_scene_transition(old_scene: str, action_key: str, result_scene: str, userdata: Userdata) -> str:
    """Record the transition into history and return a short narrative the GM can use."""
    entry = {
        "from": old_scene,
        "action": action_key,
        "to": result_scene,
        "time": datetime.utcnow().isoformat() + "Z",
    }
    userdata.history.append(entry)
    userdata.choices_made.append(action_key)
    return f"You chose '{action_key}'."

# -------------------------
# Agent Tools (function_tool)
# -------------------------

@function_tool
async def start_adventure(
    ctx: RunContext[Userdata],
    player_name: Annotated[Optional[str], Field(description="Player name", default=None)] = None,
) -> str:
    """Initialize a new Eldoria adventure session for the player and return the opening description."""
    userdata = ctx.userdata
    if player_name:
        userdata.player_name = player_name
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.inventory = []
    userdata.named_npcs = {}
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"

    opening = (
        f"Greetings {userdata.player_name or 'traveler'}. "
        f"You find yourself in the Kingdom of Eldoria as the bells ring for a missing baby dragon.\n\n"
        + scene_text("intro", userdata)
    )
    if not opening.endswith("What do you do?"):
        opening += "\nWhat do you do?"
    return opening

@function_tool
async def get_scene(
    ctx: RunContext[Userdata],
) -> str:
    """Return the current scene description (useful for 'remind me where I am')."""
    userdata = ctx.userdata
    scene_k = userdata.current_scene or "intro"
    txt = scene_text(scene_k, userdata)
    return txt

@function_tool
async def player_action(
    ctx: RunContext[Userdata],
    action: Annotated[str, Field(description="Player spoken action or the short action code (e.g., 'follow_tracks' or 'go to the forest')")],
) -> str:
    """
    Accept player's action (natural language or action key), try to resolve it to a defined choice,
    update userdata, advance to the next scene and return the GM's next description (ending with 'What do you do?').
    """
    userdata = ctx.userdata
    current = userdata.current_scene or "intro"
    scene = WORLD.get(current)
    action_text = (action or "").strip()

    if not scene:
        userdata.current_scene = "intro"
        return "The story lost its place for a moment, but the bells of Eldoria ring again.\n\n" + scene_text("intro", userdata)

    # Attempt 1: match exact action key (e.g., 'follow_tracks')
    chosen_key = None
    lower_action = action_text.lower()
    if lower_action in (scene.get("choices") or {}):
        chosen_key = lower_action

    # Attempt 2: fuzzy match by checking if action_text contains the choice key or some words from the description
    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            desc = cmeta.get("desc", "").lower()
            if cid in lower_action or any(w in lower_action for w in desc.split()[:4]):
                chosen_key = cid
                break

    # Attempt 3: keyword match against each choice description word
    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            for keyword in cmeta.get("desc", "").lower().split():
                if keyword and keyword in lower_action:
                    chosen_key = cid
                    break
            if chosen_key:
                break

    if not chosen_key:
        # If we still can't resolve, ask a clarifying GM response but keep it short and end with prompt.
        resp = (
            "Aurek the Game Master tilts his head.\n"
            "\"I could not quite follow that choice in this moment of the story. "
            "Try one of the options I mentioned, or say a simple phrase like 'follow the tracks' or 'go to the market'.\"\n\n"
            + scene_text(current, userdata)
        )
        return resp

    # Apply the chosen choice
    choice_meta = scene["choices"].get(chosen_key)
    result_scene = choice_meta.get("result_scene", current)
    effects = choice_meta.get("effects", None)

    # Apply effects (inventory/journal, etc.)
    apply_effects(effects or {}, userdata)

    # Record transition
    _note = summarize_scene_transition(current, chosen_key, result_scene, userdata)

    # Update current scene
    userdata.current_scene = result_scene

    # Build narrative reply: echo a short confirmation, then describe next scene
    next_desc = scene_text(result_scene, userdata)

    persona_pre = (
        "Aurek, your slightly dramatic but kind Game Master, narrates:\n\n"
    )
    reply = f"{persona_pre}{_note}\n\n{next_desc}"
    if not reply.endswith("What do you do?"):
        reply += "\nWhat do you do?"
    return reply

@function_tool
async def show_journal(
    ctx: RunContext[Userdata],
) -> str:
    """Summarize the session journal, inventory, and recent choices for the player."""
    userdata = ctx.userdata
    lines = []
    lines.append(f"Session: {userdata.session_id} | Started at: {userdata.started_at}")
    if userdata.player_name:
        lines.append(f"Player: {userdata.player_name}")
    if userdata.journal:
        lines.append("\nJournal entries:")
        for j in userdata.journal:
            lines.append(f"- {j}")
    else:
        lines.append("\nJournal is empty so far.")
    if userdata.inventory:
        lines.append("\nInventory:")
        for it in userdata.inventory:
            lines.append(f"- {it}")
    else:
        lines.append("\nYou carry no special items yet.")
    lines.append("\nRecent choices:")
    for h in userdata.history[-6:]:
        lines.append(f"- {h['time']} | from {h['from']} -> {h['to']} via {h['action']}")
    lines.append("\nWhat do you do?")
    return "\n".join(lines)

@function_tool
async def restart_adventure(
    ctx: RunContext[Userdata],
) -> str:
    """Reset the userdata and start again from the Eldoria bells."""
    userdata = ctx.userdata
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.inventory = []
    userdata.named_npcs = {}
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"
    greeting = (
        "Time folds like a storybook closing and opening again. "
        "The bells of Eldoria ring once more, and the decree about the missing baby dragon is shouted again.\n\n"
        + scene_text("intro", userdata)
    )
    if not greeting.endswith("What do you do?"):
        greeting += "\nWhat do you do?"
    return greeting

# -------------------------
# The Agent (GameMasterAgent)
# -------------------------
class GameMasterAgent(Agent):
    def __init__(self):
        # System instructions define Universe, Tone, Role
        instructions = """
        You are 'Aurek', the Game Master (GM) for a voice-only, Dungeons-and-Dragons-style short adventure
        set in the Kingdom of Eldoria, where a baby dragon has gone missing.

        Universe:
            - High-whimsy fantasy kingdom (Eldoria) with cozy magic, bakeries, and dragons.
        Tone:
            - Slightly dramatic, warm, and encouraging. Not grimdark or horror. A little humorous.
        Role:
            - You are the GM. You describe scenes vividly, remember the player's past choices, named NPCs,
              inventory and locations, and you always end your descriptive messages with the prompt: 'What do you do?'

        Rules:
            - Use the provided tools to start the adventure, get the current scene, accept the player's spoken action,
              show the player's journal, or restart the adventure.
            - Keep continuity using the per-session userdata. Reference journal items and inventory when relevant
              (for example, mention dragon treats if the player has them).
            - Drive short sessions (aim for several meaningful turns forming a mini-arc about finding and returning
              the baby dragon). Each GM message MUST end with 'What do you do?' so the voice UX flows naturally.
            - Respect that this agent is voice-first: responses should be concise enough for spoken delivery but still evocative.
        """
        super().__init__(
            instructions=instructions,
            tools=[start_adventure, get_scene, player_action, show_journal, restart_adventure],
        )

# -------------------------
# Entrypoint & Prewarm (keeps speech functionality)
# -------------------------
def prewarm(proc: JobProcess):
    # load VAD model and stash on process userdata, try/catch like original file
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception:
        logger.warning("VAD prewarm failed; continuing without preloaded VAD.")

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("\n" + "🐉" * 8)
    logger.info("🚀 STARTING VOICE GAME MASTER – Eldoria Baby Dragon Quest")

    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-marcus",
            style="Conversational",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=userdata,
    )

    # Start the agent session with the GameMasterAgent
    await session.start(
        agent=GameMasterAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
