# AI Gen – build a flow from a description

Click **AI Gen** in the toolbar (or press **Ctrl+G**, or *Tools → AI Gen*). A floating chat opens; describe the
inspection in plain words and the assistant builds the flow. Nothing is added to your project until you press
**Add as new flow** (or **Replace open flow**), and **Ctrl+Z** undoes it.

## First use: the API key

AI Gen calls the Anthropic API with your own key (create one in the Anthropic Console).

1. Paste the key (`sk-ant-...`) into the field. It is shown as dots.
2. Tick **Remember on this computer** to keep it in the operating system's credential store (Windows
   Credential Manager, macOS Keychain). Without it the key lives in memory until you close the app.
3. If the environment variable `ANTHROPIC_API_KEY` is set, it is used automatically.

The key is sent only to `api.anthropic.com`. It is never written to a project file, the log or the settings
file. **Remove key** (the key icon in the chat title bar) deletes the saved copy. Requests are billed to your
Anthropic account; the chat shows the tokens used. Pick the model in the same panel: Sonnet 5.5 (default),
Opus 5.5 (most capable) or Haiku 5.5 (fastest and cheapest).

## What it does

The assistant works like an engineer with the manual open:

1. It **looks things up** in the built-in reference (`vm_clone/flowgen/reference/flow_generation_reference.md`):
   concepts, port-type rules, worked recipes and one page per tool. The chat lists each lookup it made.
2. It drafts a flow **spec** (modules, parameters, links) – never raw XML.
3. It **validates** the spec. Unknown tools, ports or parameters, type mismatches, taken inputs and loops come
   back with hints and the assistant repairs them. It can also test-run the flow on synthetic input.
4. The application turns the finished spec into a real flow with its own serialiser, so the result always
   opens. You review it (modules, links, warnings) and decide.

Modules that talk to other systems or run code (TCP Send, Script, Image Output, Camera IO) are only added when
you ask for them and are called out on the flow card. Ask for changes the same way ("add a blur before the
threshold"): the assistant can read the flow that is open.

**Copy XML** and **Save XML...** give you the solution XML for any proposed flow.

## Keyboard

Ctrl+G opens/closes the chat · Enter sends · Shift+Enter adds a line · Esc stops a running reply, then closes
the panel · Tab moves between the panel's controls.

## Why there is no vector search (RAG)

The whole tool catalogue is about 3,600 tokens and the reference about 8,000. The assistant reads exactly the
sections it needs by name or keyword (`search_docs`, `read_doc`, `get_tool_spec`), which cannot miss a tool and
needs no index or embedding service. The reference is regenerated from the installed tools
(`python scripts/gen_flow_reference.py`), and a test fails if it drifts, so tools added by plugins are covered.

## Use it from other AI tools (MCP)

The same operations are available as an MCP server for Claude Desktop, Claude Code or any MCP client:

```
python main.py --mcp           # packaged build: ApexVisionStudio.exe --mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"apex-flow": {"command": "python", "args": ["C:\\path\\to\\VMClone\\main.py", "--mcp"]}}}
```

Claude Code: `claude mcp add apex-flow -- python C:\path\to\VMClone\main.py --mcp`

Tools: `search_tools`, `get_tool_spec`, `search_docs`, `read_doc`, `validate_flow`, `build_flow_xml`, `dry_run`,
`save_flow_xml` (writes only inside `projects/`); resource `apex://reference`; prompt `design_flow`.
The server calls no language model itself – the client's model does the reasoning.

## Limits

- Generated flows can be wrong. Check parameters (regions, thresholds) against your images before running.
- Only installed tools can be used. Parameters without a listed set of choices keep their defaults unless the
  assistant is told otherwise.
- Needs an internet connection and an Anthropic API key. What leaves the machine is your messages, the lookups the assistant makes and
  the flow it is working on (module names, parameters, links). Images are never sent.
