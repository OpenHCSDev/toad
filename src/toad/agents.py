from importlib.resources import files
import asyncio

from toad.agent_schema import AgentDefinition


class AgentReadError(Exception):
    """Problem reading the agents."""


async def read_agents() -> dict[str, AgentDefinition]:
    """Read agent information from data/agents

    Raises:
        AgentReadError: If the files could not be read.

    Returns:
        A mapping from identity to typed agent definitions.
    """
    import tomllib

    def read_agents() -> list[AgentDefinition]:
        """Read agent information.

        Stored in data/agents

        Returns:
            List of agent dicts.
        """
        agents: list[AgentDefinition] = []
        try:
            for file in files("toad.data").joinpath("agents").iterdir():
                agent = AgentDefinition.decode(tomllib.load(file.open("rb")))
                if agent.active:
                    agents.append(agent)

        except Exception as error:
            raise AgentReadError(f"Failed to read agents; {error}")

        return agents

    agents = await asyncio.to_thread(read_agents)
    agent_map = {agent.identity: agent for agent in agents}

    return agent_map
