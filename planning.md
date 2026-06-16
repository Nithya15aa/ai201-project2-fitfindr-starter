# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

### Tool 1: search_listings

**What it does:**
Filters the full listings dataset and returns all items that match the user's description, size, and maximum price. It scores matches using style_tags, category, and title fields and returns results sorted by relevance.

**Input parameters:**
- `description` (str): A natural language description of the item the user wants (e.g. "vintage graphic tee"). Used to match against title, description, and style_tags fields.
- `size` (str): The user's size (e.g. "M", "L"). Matched against the listing's size field exactly.
- `max_price` (float): The upper price limit. Only listings with price <= max_price are returned.

**What it returns:**
A list of listing dictionaries, sorted by relevance (best match first). Each dict contains:
- `id` (str): Unique listing identifier
- `title` (str): Item name
- `description` (str): Free text about the item
- `category` (str): One of: tops, bottoms, outerwear, shoes, accessories
- `style_tags` (list[str]): Style keywords e.g. ["vintage", "grunge"]
- `size` (str): Item size
- `condition` (str): One of: excellent, good, fair
- `price` (float): Listed price
- `colors` (list[str]): e.g. ["black", "faded grey"]
- `brand` (str or None): Brand name if known
- `platform` (str): One of: depop, thredUp, poshmark

Returns an empty list `[]` if no listings match.

**What happens if it fails or returns nothing:**
The agent stops immediately. It does not call suggest_outfit with empty input. It responds: "No listings matched your search. Try broadening your description, increasing your budget, or choosing a different size."

---

### Tool 2: suggest_outfit

**What it does:**
Takes the selected listing and the user's wardrobe and returns a styled outfit suggestion — specific pieces to pair with the new item, and how to wear them together.

**Input parameters:**
- `new_item` (dict): The listing selected from search_listings results (full listing dict with all fields as described above).
- `wardrobe` (dict): The user's existing wardrobe. Contains an `items` key with a list of wardrobe item dicts. Each wardrobe item has: `name` (str), `category` (str), `colors` (list[str]), `style_tags` (list[str]).

**What it returns:**
A string containing a specific outfit suggestion, e.g.: "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape."

**What happens if it fails or returns nothing:**
If the wardrobe is empty (items list is empty), the agent skips wardrobe-specific pairing and responds with a generic styling suggestion based on the item's style_tags and category alone. It tells the user: "We don't have your wardrobe on file, so here's a general styling idea for this piece:" followed by the suggestion.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short, shareable social media caption combining the outfit suggestion and the new item's purchase details (price, platform, condition).

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by suggest_outfit.
- `new_item` (dict): The selected listing dict (same as passed to suggest_outfit). Used to pull title, price, platform, and condition for the caption.

**What it returns:**
A string — a ready-to-share caption, e.g.: "thrifted this faded band tee off depop for $22 and honestly it was made for my wide-legs 🖤 full look in my stories"

**What happens if it fails or returns nothing:**
If `outfit` is an empty string or `new_item` is missing required fields (title, price, platform), the agent skips the fit card and tells the user: "We couldn't generate a fit card this time, but here's your outfit suggestion:" and prints the outfit string directly.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The planning loop runs sequentially with early-exit conditions at each step:

1. Receive user query. Parse it to extract: description (str), size (str), max_price (float). If any required field is missing, ask the user to clarify before proceeding.

2. Call `search_listings(description, size, max_price)`.
   - If results is empty → set error message "No listings matched..." → return early, stop here.
   - If results is non-empty → set `session["selected_item"] = results[0]` → proceed to step 3.

3. Call `suggest_outfit(new_item=session["selected_item"], wardrobe=session["wardrobe"])`.
   - If wardrobe["items"] is empty → generate generic suggestion without wardrobe pairing → set `session["outfit_suggestion"]` → proceed to step 4.
   - If wardrobe is populated → generate wardrobe-specific suggestion → set `session["outfit_suggestion"]` → proceed to step 4.

4. Call `create_fit_card(outfit=session["outfit_suggestion"], new_item=session["selected_item"])`.
   - If outfit is empty or new_item is missing fields → skip fit card → return outfit_suggestion directly.
   - If successful → set `session["fit_card"]` → return full response.

5. Return session to user: listing details + outfit suggestion + fit card caption.

---

## State Management

**How does information from one tool get passed to the next?**

A `session` dictionary is initialized at the start of each interaction and updated after each tool call. It contains:

- `session["query"]` (str): The original user query
- `session["selected_item"]` (dict): The top listing returned by search_listings. Set after step 2, passed into steps 3 and 4.
- `session["wardrobe"]` (dict): The user's wardrobe. Loaded once at session start using `get_example_wardrobe()` for returning users or `get_empty_wardrobe()` for new users.
- `session["outfit_suggestion"]` (str): The styling suggestion returned by suggest_outfit. Set after step 3, passed into step 4.
- `session["fit_card"]` (str): The final caption returned by create_fit_card. Set after step 4.
- `session["error"]` (str or None): Set if any tool returns empty or fails. Checked before each subsequent tool call to short-circuit the loop.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Stop immediately. Respond: "No listings matched your search. Try broadening your description, increasing your budget, or choosing a different size." Do not call suggest_outfit. |
| suggest_outfit | Wardrobe is empty | Continue with generic styling based on the item's style_tags. Tell the user: "We don't have your wardrobe on file, so here's a general styling idea for this piece:" |
| create_fit_card | Outfit input is missing or incomplete | Skip the fit card. Return the outfit suggestion string directly with the note: "We couldn't generate a fit card this time, but here's your outfit suggestion:" |

---

## Architecture

```
User query
    │
    ▼
Planning Loop ─────────────────────────────────────────────────┐
    │                                                          │
    ├─► search_listings(description, size, max_price)          │
    │       │                                                  │
    │       ├── results=[] ──► [STOP] "No listings found.      │
    │       │                   Try broader search." ──────────┘
    │       │
    │       └── results=[item, ...]
    │               │
    │       Session: selected_item = results[0]
    │               │
    ├─► suggest_outfit(selected_item, wardrobe)
    │       │
    │       ├── wardrobe empty ──► generic styling suggestion
    │       │
    │       └── wardrobe populated ──► wardrobe-specific suggestion
    │               │
    │       Session: outfit_suggestion = "..."
    │               │
    ├─► create_fit_card(outfit_suggestion, selected_item)
    │       │
    │       ├── missing fields ──► skip card, return outfit_suggestion directly
    │       │
    │       └── success
    │               │
    │       Session: fit_card = "..."
    │               │
    ▼
Return to user:
  - Listing (title, price, platform, condition)
  - Outfit suggestion
  - Fit card caption
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **search_listings:** Give Claude the Tool 1 spec from this file (inputs, return value, failure mode) and ask it to implement the function using `load_listings()` from `utils/data_loader.py`. Verify the generated code filters by all three parameters (description match against title/style_tags, size exact match, price <= max_price) and returns an empty list when nothing matches. Test with 3 queries: one that returns results, one with a price too low to match anything, one with an unusual size.

- **suggest_outfit:** Give Claude the Tool 2 spec and a sample `new_item` dict and `example_wardrobe` from `get_example_wardrobe()`. Ask it to implement the function and return a specific outfit string. Verify it references actual wardrobe items by name and handles an empty wardrobe without crashing.

- **create_fit_card:** Give Claude the Tool 3 spec and a sample outfit string and listing dict. Ask it to produce a casual, social-media-style caption. Verify it includes the item title, price, and platform in the output.

**Milestone 4 — Planning loop and state management:**

Give Claude the Planning Loop section and Architecture diagram from this file. Ask it to implement the planning loop as a function that initializes a session dict, calls tools in order, checks for empty results after each call, and returns the final session. Verify the generated code matches the conditional logic described above — specifically that it exits early when search_listings returns empty and does not call suggest_outfit with None or []. Test the full loop with one happy-path query and one no-results query.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
The agent parses the request and identifies: description="vintage graphic tee", size="M", max_price=30.0. It calls `search_listings("vintage graphic tee", size="M", max_price=30.0)`. If results is empty, the agent responds: "No listings matched your search. Try broadening your description, increasing your budget, or choosing a different size." and stops here.

**Step 2:**
search_listings returns 3 matching listings sorted by relevance. The agent sets `session["selected_item"] = results[0]` — "Faded Band Tee, $22, Depop, Good condition." It then calls `suggest_outfit(new_item=session["selected_item"], wardrobe=session["wardrobe"])` where wardrobe contains the user's baggy jeans and chunky sneakers.

**Step 3:**
suggest_outfit returns: "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape." The agent sets `session["outfit_suggestion"]` and calls `create_fit_card(outfit=session["outfit_suggestion"], new_item=session["selected_item"])`.

**Final output to user:**
```
Found: Faded Band Tee — $22 on Depop (Good condition)

Outfit suggestion: Pair this with your wide-leg jeans and platform Docs
for a classic 90s grunge look. Roll the sleeves once and tuck the front
corner slightly for shape.

Fit card: thrifted this faded band tee off depop for $22 and honestly
it was made for my wide-legs 🖤 full look in my stories
```