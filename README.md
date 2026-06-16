# FitFindr

A thrift shopping agent that takes a natural language query, finds matching secondhand listings, and generates a styled outfit suggestion and shareable social media caption — all in one interaction.



## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com).

Run the app:

```bash
python app.py
```

Open the URL shown in your terminal (usually `http://localhost:7860`).

To run the agent directly from the command line (tests both the happy path and the no-results path):

```bash
python agent.py
```

Run the test suite:

```bash
pytest tests/
```

---

## Tool Inventory

### `search_listings(description, size, max_price)`

**Purpose:** Filters the mock listings dataset and returns items that match the user's query, sorted by relevance.

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | `str` | Keywords describing the item (e.g. `"vintage graphic tee"`). Matched against title, description, category, and style_tags. |
| `size` | `str \| None` | Size to filter by (e.g. `"M"`, `"W30"`). Case-insensitive substring match. `None` skips size filtering. |
| `max_price` | `float \| None` | Upper price limit, inclusive. `None` skips price filtering. |

**Returns:** A list of matching listing dicts sorted by relevance score (most keyword overlaps first). Returns `[]` if nothing matches — never raises an exception.

---

### `suggest_outfit(new_item, wardrobe)`

**Purpose:** Calls the LLM to generate a specific outfit suggestion pairing the thrifted item with pieces from the user's wardrobe.

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | `dict` | The selected listing dict (title, category, colors, style_tags, condition). |
| `wardrobe` | `dict` | A dict with an `items` key containing a list of wardrobe item dicts, each with name, category, colors, and style_tags. |

**Returns:** A non-empty string with 1–2 outfit suggestions referencing wardrobe items by name. If `wardrobe["items"]` is empty, returns a general styling suggestion based on the item's tags and category instead.

Model: `llama-3.3-70b-versatile` via Groq. Temperature: `0.7`.

---

### `create_fit_card(outfit, new_item)`

**Purpose:** Generates a short, casual social media caption combining the outfit idea with the item's purchase details.

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit`. |
| `new_item` | `dict` | The selected listing dict (title, price, platform). |

**Returns:** A 2–4 sentence string suitable for an Instagram or TikTok caption. Mentions the item name, price, and platform each exactly once, in a natural tone. If `outfit` is empty or `new_item` is missing required fields, returns `"Could not generate fit card — outfit data is incomplete."` — does not raise.

Model: `llama-3.3-70b-versatile` via Groq. Temperature: `0.9` (high, for output variety across runs).

---

## How the Planning Loop Works

The agent doesn't call all three tools unconditionally. It uses a sequential planning loop with early-exit conditions at each step:

```
User query
    │
    ▼
[Parse] extract description, size, max_price from natural language
    │
    ▼
[search_listings] filter and score the listings dataset
    │
    ├── results = [] ──► SET error message, RETURN EARLY
    │                    suggest_outfit is never called
    │
    └── results found
            │
            ▼
    select top result → session["selected_item"]
            │
            ▼
    [suggest_outfit] LLM generates outfit using item + wardrobe
            │
            ├── wardrobe empty ──► generic styling suggestion (no crash)
            │
            └── wardrobe populated ──► wardrobe-specific suggestion
                    │
                    ▼
            session["outfit_suggestion"]
                    │
                    ▼
    [create_fit_card] LLM writes a shareable caption
            │
            └── success ──► session["fit_card"]
                    │
                    ▼
            Return all three results to the UI
```

**Why this matters:** When `search_listings` returns an empty list, the agent exits immediately and sets an error message. `suggest_outfit` and `create_fit_card` are not called. This is the key branch — an agent that calls all three tools unconditionally regardless of whether a listing was found is not a planning loop, it's a pipeline.

The query is parsed with regex before any tool is called. Price is extracted from patterns like `"under $30"` or `"below $40"`. Size is extracted from `"size M"` or `"in XL"`. The remaining text becomes the keyword description for `search_listings`.

---

## State Management

A `session` dict is initialized at the start of each `run_agent()` call and updated after each tool. Nothing is re-fetched or re-computed between steps — every tool reads from and writes to this single object.

```python
session = {
    "query":             "vintage graphic tee under $30",   # original input
    "parsed":            {"description": "...", "size": None, "max_price": 30.0},
    "search_results":    [...],        # all matching listings
    "selected_item":     {...},        # results[0], passed into steps 5 and 6
    "wardrobe":          {...},        # loaded once at session start
    "outfit_suggestion": "...",        # from suggest_outfit, passed into step 6
    "fit_card":          "...",        # from create_fit_card
    "error":             None,         # set on early exit, checked before each step
}
```

The flow of data between tools:
- `selected_item` is set in step 4 and passed as `new_item` to both `suggest_outfit` and `create_fit_card`.
- `outfit_suggestion` is set in step 5 and passed as `outfit` to `create_fit_card`.
- Neither LLM tool re-reads the listings dataset or re-parses the query.

---

## Error Handling

| Tool | Failure mode | What the agent does |
|------|-------------|---------------------|
| `search_listings` | No listings match the query | Sets `session["error"]`: *"No listings matched your search. Try broadening your description, increasing your budget, or choosing a different size."* Returns immediately. `suggest_outfit` is never called. |
| `suggest_outfit` | `wardrobe["items"]` is empty | Continues — sends a different prompt asking for general styling advice based on the item's style tags and category. Returns a non-empty string. Does not crash or return `""`. |
| `create_fit_card` | `outfit` is empty string or `new_item` missing title/price/platform | Returns the string `"Could not generate fit card — outfit data is incomplete."` Does not raise an exception. |

**Concrete example from testing:**

Query: `"designer ballgown size XXS under $5"`

`search_listings("designer ballgown", size="XXS", max_price=5.0)` returned `[]` — no listing in the dataset is under $5 or tagged as ballgown. The agent set `session["error"]` to the no-results message and returned. `session["selected_item"]`, `session["outfit_suggestion"]`, and `session["fit_card"]` all remained `None`. The Gradio UI displayed the error message in the first panel and left the other two panels empty.

---

## AI Usage

### Instance 1 — `search_listings` implementation

**What I gave the AI:** The Tool 1 spec block from `planning.md` — inputs with types, return value description, failure mode (return `[]`, never raise), and the instruction to use `load_listings()` from `utils/data_loader.py`.

**What it produced:** A working implementation that loaded listings, filtered by price and size, and scored by keyword overlap.

**What I changed:** The original generated code used an exact size match (`listing["size"] == size`). I changed it to a case-insensitive substring match (`size.lower() in listing_size`) so that a query for `"M"` would match listings sized `"S/M"` or `"M/L"`, which is more realistic for secondhand shopping.

### Instance 2 — `run_agent()` planning loop

**What I gave the AI:** The full Planning Loop section and Architecture diagram from `planning.md`, including the explicit early-exit condition after `search_listings` and the session dict schema.

**What it produced:** A working planning loop with regex-based query parsing, sequential tool calls, and session state updates.

**What I changed:** The initial generated regex didn't handle price patterns without a `$` sign (e.g. `"under 30"`) or `"budget: $40"` style phrasing. I extended the regex to cover additional natural language price patterns. I also reviewed that `suggest_outfit` was only called after confirming `session["search_results"]` was non-empty — the generated code had this correct, but I verified it explicitly before accepting.

---

## Spec Reflection

**What matched your spec:** The three-tool sequential structure matched exactly. State passing via the session dict worked as planned — `selected_item` flows cleanly from step 4 into both downstream LLM calls without any re-fetching.

**What you'd change:** The query parser is regex-based, which works for structured queries but breaks on more conversational phrasing like *"I'm thinking something flowy and vintage, nothing too expensive."* A better approach would be an LLM-based parsing step that extracts structured fields (description, size, max_price) from free-form text before calling `search_listings`. This would make the agent more robust to natural language variation without changing any of the tool interfaces.

**What surprised you:** The empty wardrobe path in `suggest_outfit` was more useful than expected — the LLM generated genuinely good general styling advice based on style tags alone, which means a new user without a wardrobe on file still gets a useful response rather than a fallback message.
