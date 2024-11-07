from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Union
from typing_extensions import Self

from pydantic import BaseModel, model_validator

from wazuh.core.exception import WazuhError
from wazuh.core.indexer.bulk import Operation
from wazuh.core.indexer.commands import CommandsManager
from wazuh.core.indexer.models.commands import Result

FIM_INDEX = 'wazuh-states-fim'
INVENTORY_NETWORK_INDEX = 'wazuh-states-inventory-network'
INVENTORY_PACKAGES_INDEX = 'wazuh-states-inventory-packages'
INVENTORY_PROCESSES_INDEX = 'wazuh-states-inventory-processes'
INVENTORY_SYSTEM_INDEX = 'wazuh-states-inventory-system'
SCA_INDEX = 'wazuh-states-sca'
VULNERABILITY_INDEX = 'wazuh-states-vulnerabilities'
INVENTORY_NETWORK_TYPE = 'network'
INVENTORY_PACKAGES_TYPE = 'package'
INVENTORY_PROCESSES_TYPE = 'process'
INVENTORY_SYSTEM_TYPE = 'system'


@dataclass
class AgentMetadata:
    """Agent metadata."""
    uuid: str
    groups: List[str]
    os: str
    platform: str
    arch: str
    type: str
    version: str
    ip: str


@dataclass
class TaskResult:
    """Stateful event bulk task result data model."""
    id: str
    result: str
    status: int


class Hash:
    """Hash data model."""
    md5: str = None
    sha1: str = None
    sha256: str = None


class File:
    """File data model."""
    attributes: List[str] = None
    name: str = None
    path: str = None
    gid: int = None
    group: str = None
    inode: str = None
    mtime: datetime = None
    mode: str = None
    size: float = None
    target_path: str = None
    type: str = None
    uid: int = None
    owner: str = None
    hash: Hash = None


class Registry:
    """Registry data model."""
    key: str = None
    value: str = None


class FIMEvent(BaseModel):
    """FIM events data model."""
    file: File = None
    registry: Registry = None


class InventoryNetworkEvent(BaseModel):
    """Inventory network events data model."""
    # TODO(25121): Add inventory network fields once they are defined


class OS:
    """OS data model."""
    kernel: str = None
    full: str = None
    name: str = None
    platform: str = None
    version: str = None
    type: str = None


class Host:
    """Host data model."""
    architecture: str = None
    hostname: str = None
    os: OS = None


class Package:
    """Package data model."""
    architecture: str = None
    description: str = None
    installed: datetime = None
    name: str = None
    path: str = None
    size: float = None
    type: str = None
    version: str = None


class InventoryPackageEvent(BaseModel):
    """Inventory packages events data model."""
    scan_time: datetime = None
    package: Package = None


class Parent:
    """Process parent data model."""
    pid: float = None


class ID:
    """Process users and groups ID data model."""
    id: str = None


class Process:
    """Process data model."""
    pid: float = None
    name: str = None
    parent: Parent = None
    command_line: str = None
    args: List[str] = None
    user: ID = None
    real_user: ID = None
    saved_user: ID = None
    group: ID = None
    real_group: ID = None
    saved_group: ID = None
    start: datetime = None
    thread: ID = None


class InventoryProcessEvent(BaseModel):
    """Inventory process events data model."""
    scan_time: datetime = None
    process: Process = None


class InventorySystemEvent(BaseModel):
    """Inventory system events data model."""
    scan_time: datetime = None
    host: Host = None


class SCAEvent(BaseModel):
    """SCA events data model."""
    # TODO(25121): Add SCA event fields once they are defined


class VulnerabilityEventHost:
    """Host data model in relation to vulnerability events."""
    os: OS = None


class VulnerabilityEventPackage:
    """Package data model in relation to vulnerability events."""
    architecture: str = None
    build_version: str = None
    checksum: str = None
    description: str = None
    install_scope: str = None
    installed: datetime = None
    license: str = None
    name: str = None
    path: str = None
    reference: str = None
    size: float = None
    type: str = None
    version: str = None


class Cluster:
    """Wazuh cluster data model."""
    name: str = None
    node: str = None


class Schema:
    """Wazuh schema data model."""
    version: str = None


class Wazuh:
    """Wazuh instance information data model."""
    cluster: Cluster = None
    schema: Schema = None


class Scanner:
    """Scanner data model."""
    source: str = None
    vendor: str = None


class Score:
    """Score data model."""
    base: float = None
    environmental: float = None
    temporal: float = None
    version: str = None


class VulnerabilityEvent(BaseModel):
    """Vulnerability events data model."""
    host: VulnerabilityEventHost = None
    package: VulnerabilityEventPackage = None
    scanner: Scanner = None
    score: Score = None
    category: str = None
    classification: str = None
    description: str = None
    detected_at: datetime = None
    enumeration: str = None
    id: str = None
    published_at: datetime = None
    reference: str = None
    report_id: str = None
    severity: str = None
    under_evaluation: bool = None


class CommandResult(BaseModel):
    """Command result data model."""
    result: Result


class ModuleName(str, Enum):
    """Stateful event module name."""
    FIM = 'fim'
    INVENTORY = 'inventory'
    SCA = 'sca'
    VULNERABILITY = 'vulnerability'
    COMMAND = 'command'


class Module:
    """Stateful event module."""
    name: ModuleName
    type: str = None


class StatefulEvent(BaseModel):
    """Stateful event data model."""
    document_id: str
    operation: Operation
    module: Module
    data: Union[
        FIMEvent,
        InventoryNetworkEvent,
        InventoryPackageEvent,
        InventoryProcessEvent,
        InventorySystemEvent,
        SCAEvent,
        VulnerabilityEvent,
        CommandResult
    ] = None

    @model_validator(mode='after')
    def validate_model_fields(self) -> Self:
        """Validate the model fields depending on the operation performed."""
        if self.operation == Operation.CREATE or self.operation == Operation.UPDATE:
            assert self.data is not None
        
        if self.operation == Operation.CREATE:
            assert self.data.model_fields_set
        
        if self.operation == Operation.DELETE:
            assert self.data is None
                
        return self


STATEFUL_EVENTS_INDICES: Dict[ModuleName, str] = {
    ModuleName.FIM: FIM_INDEX,
    ModuleName.SCA: SCA_INDEX,
    ModuleName.VULNERABILITY: VULNERABILITY_INDEX,
    ModuleName.COMMAND: CommandsManager.INDEX
}


def get_module_index_name(module: Module) -> str:
    """Get the index name corresponding to the specified module.

    Parameters
    ----------
    module : Module
        Event module.
    
    Raises
    ------
    WazuhError(1763)
        Invalid inventory module type error.
    WazuhError(1765)
        Invalid module name.
    
    Returns
    -------
    str
        Index name.
    """
    if module.name == ModuleName.INVENTORY:
        if module.type == INVENTORY_PACKAGES_TYPE:
            return INVENTORY_PACKAGES_INDEX
        if module.type == INVENTORY_PROCESSES_TYPE:
            return INVENTORY_PROCESSES_INDEX
        if module.type == INVENTORY_NETWORK_TYPE:
            return INVENTORY_NETWORK_INDEX
        if module.type == INVENTORY_SYSTEM_TYPE:
            return INVENTORY_SYSTEM_INDEX

        raise WazuhError(1763)

    try:
        return STATEFUL_EVENTS_INDICES[module.name]
    except KeyError:
        raise WazuhError(1765)
