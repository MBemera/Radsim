"""Minimal RadSim extension API v1 example."""


def setup(api):
    storage = api.get_extension_storage()

    def targeted_test_hint(tool_input):
        changed_file = tool_input["changed_file"]
        stem = changed_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return {
            "success": True,
            "hint": f"Start with tests matching: test_{stem}.py",
        }

    api.register_tool(
        {
            "name": "targeted_test_hint",
            "description": "Suggest a focused pytest filename for a changed source file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "changed_file": {
                        "type": "string",
                        "description": "Relative source filename",
                    }
                },
                "required": ["changed_file"],
            },
        },
        targeted_test_hint,
        permission_tier="read_only",
    )

    def show_status(agent):
        print(f"  Targeted Tests observed {storage.get('tool_calls', 0)} tool call(s).")

    api.register_command(
        "targeted-tests",
        show_status,
        "Show Targeted Tests extension status",
    )

    def count_tool_calls(context):
        storage["tool_calls"] = int(storage.get("tool_calls", 0)) + 1

    api.on("post_tool", count_tool_calls)
