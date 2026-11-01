"""The assistant's application tools (US 110), declared for Gemini function calling.

Each tool only *asks* for an action. The assistant router hands the call to the
applications package, which turns it into a checked proposal; the traveler sees
it and confirms it before anything is saved. The model never writes anything,
and there is no tool that submits.
"""

from .assistant import DEFAULT_MODEL, AskTools, AssistantUnavailable, ModelTurn, REFUSAL_REPLY, blocked, generate

_QUESTION_ID = {"type": "string", "description": "A question id from the application's question list."}

TOOLS: list[dict] = [
    {
        "name": "change_answer",
        "description": ("Prepare a change to one of the traveler's answers, only when they ask for it. "
                        "The traveler reviews and confirms the change before it is saved."),
        "parameters": {
            "type": "object",
            "properties": {
                "question_id": _QUESTION_ID,
                "value": {"type": "string", "description": (
                    "The new answer: a choice value from the list, yes or no, a date as YYYY-MM-DD, "
                    "a country as its 3-letter code, or plain text.")},
            },
            "required": ["question_id", "value"],
        },
    },
    {
        "name": "go_to_question",
        "description": "Take the traveler to a question they have answered, or to the current one.",
        "parameters": {"type": "object", "properties": {"question_id": _QUESTION_ID}, "required": ["question_id"]},
    },
    {
        "name": "run_completeness_check",
        "description": "Check what is missing or inconsistent in the application before submission.",
        "parameters": {"type": "object", "properties": {}},
    },
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}

TOOLS_PROMPT = (
    "You can act in this application with tools, but only when the traveler asks you to: change_answer to "
    "prepare a new answer, go_to_question to take them to a question, run_completeness_check to see what is "
    "missing. Use a question id from the list above. A tool call only prepares the action: the traveler "
    "sees it and confirms it before anything is saved, so say \"here's the change, confirm it below\", never "
    "\"I've changed it\". Never change an answer they didn't ask to change. Nothing is ever submitted to an "
    "embassy from this chat."
)


def gemini_ask_tools(client, model: str = DEFAULT_MODEL) -> AskTools:
    """An AskTools backed by the Gemini API (`google.genai.Client`)."""

    def ask(system: str, messages: list[dict]) -> ModelTurn:
        response = generate(client, model, system, messages, TOOLS)
        call = None
        for found in response.function_calls or []:
            if found.name in TOOL_NAMES:
                call = (found.name, dict(found.args or {}))
                break
        # Read the text parts directly: `response.text` warns when a reply also holds a function call.
        parts = (response.candidates[0].content.parts or []) if response.candidates and response.candidates[0].content else []
        text = "".join(part.text for part in parts if getattr(part, "text", None)).strip()
        if call or text:
            return ModelTurn(text, call)
        if blocked(response):
            return ModelTurn(REFUSAL_REPLY)
        raise AssistantUnavailable

    return ask
