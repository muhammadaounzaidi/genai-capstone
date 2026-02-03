# MCP Agent Flow — How Everything Is Integrated

This document describes how the **MCP agent** (Pydantic AI + FastMCP) is wired: from Discord message to tools, state, and back to the user.

---

## 1. High-Level Flow

```
User (Discord) → GroomingBot → MCPAgent.process_message()
                                    ↓
                    [First message?] → create_lead (Sheets)
                                    ↓
                    AgentDeps (user_id, username, last_state)
                                    ↓
                    Pydantic AI Agent.run(message, deps, message_history)
                                    ↓
                    LLM may call MCP tools (lead / services / booking)
                                    ↓
                    build_state_from_sheets() → new state
                                    ↓
                    Return { response, state, lead_created } → Discord
```

---

## 2. Entry Point & Configuration

| Component | Role |
|-----------|------|
| **`main.py`** | Reads `Config.AGENT_TYPE` (env `AGENT_TYPE`). If `"mcp"`, passes `agent_type="mcp"` to `GroomingBot`. |
| **`config.py`** | `AGENT_TYPE = os.getenv("AGENT_TYPE", "langgraph")` — set `AGENT_TYPE=mcp` in `.env` to use the MCP agent. |
| **`discord_bot.py`** | `GroomingBot(agent_type=...)` → `_create_agent()` returns `MCPAgent(sheets_service, calendar_service)` when `agent_type == "mcp"`. |

So: **main → config → Discord bot → MCPAgent** when using the MCP agent.

---

## 3. Discord Bot → MCPAgent

When a user sends a message (DM or mention):

1. **`on_message`** gets `user_id`, `username`, `message.content`, `conversation_history`, and `last_state` (from `last_state_by_user[user_id]`).
2. It calls **`agent.process_message(user_id, username, message, conversation_history, last_state)`**.
3. For MCP agent, that is **`MCPAgent.process_message()`**.
4. The bot stores **`result["state"]`** in `last_state_by_user[user_id]` and sends **`result["response"]`** to the user.

So the bot only knows: call `process_message`, then use `response` and `state`. All MCP/agent logic lives inside `MCPAgent`.

---

## 4. MCPAgent (`agents/mcp_agent/agent.py`)

### 4.1 Initialization

- **`__init__(sheets_service, calendar_service)`**
  - Stores `sheets_service` and `calendar_service`.
  - Calls **`create_grooming_agent(sheets_service, calendar_service)`** and keeps the Pydantic AI `Agent` as `self._agent`.

### 4.2 `process_message()` Flow

1. **Previous state**  
   `prev = last_state or {}`.  
   `message_history = prev.get("pydantic_message_history")` — this is the Pydantic AI message history for continuity.

2. **First message**  
   If there is no `message_history` and no prior conversation, the agent calls **`sheets_service.create_lead(user_id, username, message)`** so the lead row exists before the model runs.

3. **Dependencies**  
   Builds **`AgentDeps`** from `prev`:
   - `user_id`, `username`
   - `collected_info`, `lead_qualified`, `appointment_booked`, `service_selected`

4. **Run the agent**  
   **`await self._agent.run(message, deps=deps, message_history=message_history)`**  
   The LLM can call MCP tools; each tool receives parameters (including `user_id` from deps via dynamic instructions).

5. **After the run**  
   - `response_text = result.output` (or fallback).
   - **`new_state = build_state_from_sheets(self.sheets_service, user_id, username, prev)`** — state is derived from Sheets (and `prev`), not from the LLM.
   - `new_state` is extended with:
     - `pydantic_message_history = result.all_messages()` (for next turn),
     - `last_interaction_at`, `reminder_sent`.

6. **Return**  
   `{ "response": response_text, "state": new_state, "lead_created": new_state.get("lead_created", True) }`.

So: **MCPAgent** = first-message lead creation + building deps + running the Pydantic AI agent + building state from Sheets and returning a single response/state object.

---

## 5. Pydantic AI Agent (`create_grooming_agent`)

- **Model:** `google-gla:gemini-2.5-flash` (uses `Config.GOOGLE_API_KEY`).
- **Deps type:** `AgentDeps` (user_id, username, collected_info, lead_qualified, appointment_booked, service_selected).
- **Output:** `str` (the reply to the user).
- **System prompt:** From **`agents/mcp_agent/prompts.py`** (`SYSTEM_PROMPT`).
- **Tools:** Three **FastMCPToolsets**:
  1. **Lead** — `create_lead_mcp_server(sheets_service)`
  2. **Services** — `create_services_mcp_server(sheets_service)`
  3. **Booking** — `create_booking_mcp_server(sheets_service, calendar_service)`

**Dynamic instructions** (via `@agent.instructions`):

- Injects: “The current user’s user_id is … username is …”
- Tells the model to always pass this `user_id` (and `username` for lead_create_lead) when calling lead tools.
- Appends **`format_collected_info(deps.collected_info)`** so the model knows what’s already collected.
- If `lead_qualified` and `appointment_booked`, adds a note to use `booking_update_appointment_service` for service changes.

So the **agent** is: system prompt + three MCP toolsets + dependency-driven instructions. It does not build state; that’s done in `state_builder` after the run.

---

## 6. FastMCP Servers (Tools)

All live under **`agents/mcp_agent/servers/`**. Each server is a **FastMCP** instance; Pydantic AI wraps them as **FastMCPToolset** and the LLM calls them by name.

### 6.1 Shared utility (`tool_utils.py`)

- **`run_tool(fn, fallback, logger, log_message)`**  
  Runs `fn()`; on success returns its dict (or `fallback` if not a dict); on exception logs and returns `{**fallback, "error": str(error)}`.  
  Keeps tool handlers DRY and consistent.

### 6.2 Lead server (`lead.py`)

- **`create_lead_mcp_server(sheets_service)`** → FastMCP `"grooming-lead"`.
- Tools (all use `user_id` from injected instructions):

| Tool | Purpose | Sheets used |
|------|---------|-------------|
| `lead_create_lead` | Create lead row (first message is also created by MCPAgent before run) | `create_lead` |
| `lead_qualify_lead` | Update lead with name, phone, city, pet details | `qualify_lead` |
| `lead_update_lead_status` | Set status (e.g. `"booked"`) | `update_lead_status` |
| `lead_get_lead_id` | Get current user’s `lead_id` (for booking) | `get_lead_id_for_user` |
| `lead_exists` | Check if lead exists for user | `lead_exists` |

### 6.3 Services server (`services.py`)

- **`create_services_mcp_server(sheets_service)`** → FastMCP `"grooming-services"`.

| Tool | Purpose | Sheets used |
|------|---------|-------------|
| `services_get_services` | List all services (id, title, price, duration) | `get_services` |
| `services_get_brand_config` | Hours, location, address, contact | `get_brand_config` |
| `services_get_service_by_name_or_id` | Resolve name/ID to service record and `service_id` | `get_service_with_id` |

### 6.4 Booking server (`booking.py`)

- **`create_booking_mcp_server(sheets_service, calendar_service)`** → FastMCP `"grooming-booking"`.

| Tool | Purpose | Backend |
|------|---------|---------|
| `booking_list_available_slots` | List slots (next 7 days, business hours) | `GoogleCalendarService.list_available_slots` + `_format_slots` |
| `booking_create_calendar_event` | Create calendar event; returns `event_id` | `GoogleCalendarService.create_event` |
| `booking_create_appointment` | Create appointment row (lead_id, start/end, service_id, calendar_event_id) | `GoogleSheetsService.create_appointment` |
| `booking_update_appointment_service` | Change service for existing appointment | `GoogleSheetsService.update_appointment_service` |
| `booking_get_appointment_by_lead_id` | Get appointment for lead | `GoogleSheetsService.get_appointment_by_lead_id` |

Booking flow (orchestrated by the prompt): get `lead_id` → create calendar event → create appointment → update lead status to `"booked"`.

---

## 7. State Builder (`agents/mcp_agent/state_builder.py`)

State is **not** returned by the LLM; it’s computed after each turn for Discord bot compatibility.

### 7.1 `format_collected_info(collected_info)`

- Used **only** by the Pydantic AI agent’s dynamic instructions.
- Turns `collected_info` dict into a string like “INFORMATION ALREADY COLLECTED: …” so the model doesn’t re-ask for name, phone, pet, etc.

### 7.2 `build_state_from_sheets(sheets_service, user_id, username, prev)`

- Used by **MCPAgent** after each `agent.run()`.
- Reads **from Sheets**:
  - `lead_created` = `sheets_service.lead_exists(user_id)`
  - `status` = `sheets_service.get_lead_status(user_id)` → drives `lead_qualified`
  - `lead_id` = `sheets_service.get_lead_id_for_user(user_id)`
  - `appointment` = `sheets_service.get_appointment_by_lead_id(lead_id)` → drives `appointment_booked`, `service_selected`
- Merges with **`prev`** (e.g. `messages`, `collected_info`, `reminder_sent`) and returns the full state dict the Discord bot expects.

So: **state_builder** = single place that maps “Sheets + prev” → bot state. The LLM only produces the reply text; tools mutate Sheets, and state is derived from Sheets.

---

## 8. Prompts (`agents/mcp_agent/prompts.py`)

- **`SYSTEM_PROMPT`**: One constant with the full system prompt (greeting, lead qualification, services listing, booking flow, update-booking flow, no placeholders, etc.).
- **Single responsibility:** All prompt text lives here; the agent only imports and uses it.

---

## 9. Backend Services

| Service | Used by | Role |
|---------|---------|------|
| **GoogleSheetsService** | MCPAgent (first-message lead, create_lead), all three MCP servers, state_builder | Leads, Services, Brand config, Appointments |
| **GoogleCalendarService** | Booking MCP server only | List slots, create events |

Sheets is the source of truth for leads and appointments; calendar is used only for availability and event creation.

---

## 10. Data Flow Summary

1. **Discord** sends message → **GroomingBot** → **MCPAgent.process_message(...)**.
2. **MCPAgent** optionally creates lead on first message, builds **AgentDeps** from **last_state**, runs **Pydantic AI agent** with **prompts.SYSTEM_PROMPT** and **dynamic instructions** (including **format_collected_info**).
3. **Pydantic AI** may call **FastMCP** tools (lead / services / booking); tools use **tool_utils.run_tool** and **GoogleSheetsService** / **GoogleCalendarService**.
4. After **agent.run()**, **MCPAgent** calls **build_state_from_sheets(sheets_service, user_id, username, prev)** and attaches **result.all_messages()** to state.
5. Bot saves **state** and sends **response** to Discord.

So: **Entry (main/config/discord) → MCPAgent (orchestration + agent run) → Pydantic AI + 3 MCP servers (tools) → state_builder (state from Sheets) → back to Discord.**

---

## 11. File Map (MCP Agent)

| Path | Responsibility |
|------|----------------|
| `main.py` | Entry; reads AGENT_TYPE, starts bot |
| `config.py` | AGENT_TYPE, API keys, sheet/calendar IDs |
| `discord_bot.py` | GroomingBot, on_message, state storage, agent creation (LangGraph vs MCP) |
| `agents/base.py` | BaseAgent interface |
| `agents/mcp_agent/agent.py` | AgentDeps, create_grooming_agent, MCPAgent |
| `agents/mcp_agent/prompts.py` | SYSTEM_PROMPT |
| `agents/mcp_agent/state_builder.py` | format_collected_info, build_state_from_sheets |
| `agents/mcp_agent/servers/__init__.py` | Exposes create_*_mcp_server |
| `agents/mcp_agent/servers/tool_utils.py` | run_tool (DRY error handling) |
| `agents/mcp_agent/servers/lead.py` | Lead FastMCP + tools |
| `agents/mcp_agent/servers/services.py` | Services FastMCP + tools |
| `agents/mcp_agent/servers/booking.py` | Booking FastMCP + tools |
| `services/google_sheets_service.py` | All Sheets access (leads, services, brand, appointments) |
| `services/google_calendar_service.py` | Slots, create event |

This is how the MCP agent flow is integrated end to end.
