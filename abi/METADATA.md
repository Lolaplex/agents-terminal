# Side-effect metadata

`python -m agents_terminal --help-json` is the manifest. Every object under `commands` declares one fact in three places so a harness can classify a tool without a special case for this package.

`side_effects` is canonical.

| Field | Read-only command | Mutating command |
| --- | --- | --- |
| `side_effects` | `"read-only"` | `"mutating"` |
| `mutates` | `false` | `true` |
| `annotations.readOnlyHint` | `true` | `false` |
| `annotations.destructiveHint` | `false` | `true` |
| `annotations.idempotentHint` | `true` | `false` |
| `annotations.openWorldHint` | `false` | `true` for `run` |

`mutates` is true if and only if `side_effects` is `mutating`. `annotations.readOnlyHint` is true if and only if `side_effects` is `read-only`. `annotations.destructiveHint` is true if and only if `side_effects` is `mutating`. If those views ever disagree, trust `side_effects`.

Missing `side_effects` metadata means mutating. A command with no `side_effects` field, an unknown value, or any value other than exactly `read-only` is mutating even when `mutates` is false or `annotations.readOnlyHint` is true. `run` stays mutating.

Do not infer the class from the command name.

The top-level `classification` object repeats the field names:

```json
{
  "field": "side_effects",
  "enum": ["read-only", "mutating"],
"boolean_field": "mutates",
    "annotation": "annotations.readOnlyHint",
    "missing": "mutating"
  }
```

## Classes

`read-only` means the command only observes paths inside the workspace root. It does not create, modify, or delete anything, and it does not spawn a process.

`mutating` means the command may change state or execute arbitrary argv.

| Command | `side_effects` |
| --- | --- |
| `list` | `read-only` |
| `read` | `read-only` |
| `grep` (alias `search`) | `read-only` |
| `stat` | `read-only` |
| `run` | `mutating` |

`annotations` uses the MCP tool annotation names `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint`. They describe the same fact as `side_effects`. They are not a second policy.

## Example

```json
{
  "classification": {
    "field": "side_effects",
    "enum": ["read-only", "mutating"],
    "boolean_field": "mutates",
    "annotation": "annotations.readOnlyHint",
    "missing": "mutating"
  },
  "commands": {
    "read": {
      "side_effects": "read-only",
      "mutates": false,
      "annotations": {
        "readOnlyHint": true,
        "destructiveHint": false,
        "idempotentHint": true,
        "openWorldHint": false
      }
    },
    "run": {
      "side_effects": "mutating",
      "mutates": true,
      "annotations": {
        "readOnlyHint": false,
        "destructiveHint": true,
        "idempotentHint": false,
        "openWorldHint": true
      }
    }
  }
}
```

Each command also has `usage`, `description`, and a JSON Schema `parameters` object. `grep` has `aliases: ["search"]`. The alias is the same command, not a second class.
