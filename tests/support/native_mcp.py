"""MCP declarations and project trust written through the native package's own code, for inventory tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

DECLARE = r"""
import { pathToFileURL } from 'node:url';
const [packageRoot, projectRoot, agentDir, trusted, initialize] = process.argv.slice(1);
const { ProjectTrustStore } = await import(pathToFileURL(packageRoot + '/dist/index.js'));
const { writeNativeServer } = await import(pathToFileURL(packageRoot + '/agent-comms-extensions/pi-mcp-client/src/config-write.mjs'));
const trust = new ProjectTrustStore(agentDir);
if (initialize === 'true') {
  trust.set(projectRoot, true);
  for (const scope of ['user', 'project']) {
    await writeNativeServer({ agentDir, projectRoot, configDirName: '.pi', scope,
      declaration: { id: 'fixture', enabled: true, instructionsPolicy: 'status-only',
        transport: { type: 'stdio', command: 'never-launched', args: ['HIDDEN_ARGUMENT'], cwd: 'project',
          envFrom: { CHILD: 'HOST' } } }});
  }
}
trust.set(projectRoot, trusted === 'true');
"""


def declare_fixture_server(package: Path, project: Path, agent_dir: Path, *, trusted: bool) -> None:
    """Declare one stdio server ``fixture`` for the user and the project (first call only) and set
    whether the project is trusted. The server command is never started."""
    first = not (project / ".pi/mcp.json").exists()
    subprocess.run(["node", "--input-type=module", "-e", DECLARE, str(package), str(project), str(agent_dir),
                    str(trusted).lower(), str(first).lower()], check=True, timeout=10)
