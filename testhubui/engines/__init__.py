"""
TestHub Automation Studio — engine registry.

Adding a capability to the rail is: write a module implementing the Engine
contract in base.py, then import it here. Nothing else in the codebase changes.
"""

from .base import (Assets, Row, WouldClobber, catalog, field, get, register,  # noqa: F401
                   section, write)

# Registration happens on import. Each engine declares its own honest
# emits_assets / can_execute, so the rail can never claim a capability the
# machine cannot actually deliver.
from . import contract_first   # noqa: F401,E402  (requirements assurance — validates the oracle)
from . import ui_playwright    # noqa: F401,E402
from . import salesforce       # noqa: F401,E402
from . import mobile_mobilewright  # noqa: F401,E402
from . import perf_k6          # noqa: F401,E402
from . import security_zap     # noqa: F401,E402
from . import security_garak  # noqa: F401,E402
from . import agent_trust      # noqa: F401,E402  (registers Agentforce + AI Agentic)
from . import agentforce_config  # noqa: F401,E402  (edits the framework's agentforce.config.ts)

__all__ = ['Assets', 'Row', 'WouldClobber', 'catalog', 'field', 'get', 'register', 'section', 'write']
