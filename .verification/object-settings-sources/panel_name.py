import json
from pathlib import Path
r=Path.cwd()
p={'recipes':[{'recipe_id':'name-the-session-settings-distinctly-from-agent-defaults','operations':[{'operation':'patch_target','file_path':str(r/'src/toad/configured_view.py'),'target_qualname':'AgentProperties.panel','replacements':[{'old_source':'SideBar.Panel("Agent settings", cls(view),','new_source':'SideBar.Panel("Session settings", cls(view),'}]}]}]}
Path('.verification/object-settings-sources/panel-name.plan.json').write_text(json.dumps(p,indent=2))
