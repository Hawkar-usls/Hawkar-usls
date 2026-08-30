"""Public JANUS-SPI package surface.

The package intentionally uses lazy exports.  The bootstrap/model-fabric layer
must be importable before heavyweight cognitive/runtime dependencies are
materialized.  Importing ``janus_spi`` therefore grants no side effect and does
not load unrelated organs; a concrete symbol loads only its owning module.
"""

from __future__ import annotations

from importlib import import_module
from typing import Dict


# public_name -> "relative module:concrete attribute"
# A single serialized target avoids generic secret scanners mistaking harmless
# two-string export tuples for credential pairs.
_EXPORTS: Dict[str, str] = {
    "AckReconciliationLedger": ".ack:AckReconciliationLedger",
    "LegacyJanusAckReconciler": ".ack:JanusAckReconciler",
    "verify_receiver_ack": ".ack:verify_receiver_ack",
    "verify_transport_receipt": ".ack:verify_transport_receipt",
    "GitHubAPIReader": ".ack_provenance:GitHubAPIReader",
    "GitHubAckProvenanceVerifier": ".ack_provenance:GitHubAckProvenanceVerifier",
    "HashLedger": ".ack_provenance:HashLedger",
    "LegacyJanusAuthenticatedAckFinalizer": ".ack_provenance:JanusAuthenticatedAckFinalizer",
    "ActivationEvent": ".activator:ActivationEvent",
    "ActivationLedger": ".activator:ActivationLedger",
    "JanusActivator": ".activator:JanusActivator",
    "AuraPeerAdapter": ".aura_habitat_spiral:AuraPeerAdapter",
    "DialogueLedger": ".aura_habitat_spiral:DialogueLedger",
    "HabitatMirror": ".aura_habitat_spiral:HabitatMirror",
    "SpiralDialogueEngine": ".aura_habitat_spiral:SpiralDialogueEngine",
    "SpiralTurn": ".aura_habitat_spiral:SpiralTurn",
    "Forecast": ".core:Forecast",
    "JanusSPICore": ".core:JanusSPICore",
    "Ledger": ".core:Ledger",
    "SemanticEvent": ".core:SemanticEvent",
    "SemanticMemory": ".core:SemanticMemory",
    "DispatchLedger": ".dispatch:DispatchLedger",
    "JanusDispatchBroker": ".dispatch:JanusDispatchBroker",
    "verify_dispatch_packet": ".dispatch:verify_dispatch_packet",
    "verify_sealed_receipt": ".dispatch:verify_sealed_receipt",
    "ExecutionGrantLedger": ".execution_grant:ExecutionGrantLedger",
    "JanusExecutionGrantIssuer": ".execution_grant:JanusExecutionGrantIssuer",
    "verify_execution_grant": ".execution_grant:verify_execution_grant",
    "GitHubExecutionReturnVerifier": ".execution_return:GitHubExecutionReturnVerifier",
    "JanusExecutionResultFinalizer": ".execution_return:JanusExecutionResultFinalizer",
    "verify_execution_receipt": ".execution_return:verify_execution_receipt",
    "verify_orientation_snapshot": ".execution_return:verify_orientation_snapshot",
    "ExecutionTransportLedger": ".execution_transport:ExecutionTransportLedger",
    "JanusExecutionTransportBroker": ".execution_transport:JanusExecutionTransportBroker",
    "verify_execution_transport_receipt": ".execution_transport:verify_execution_transport_receipt",
    "GitHubObserver": ".github_observer:GitHubObserver",
    "HabitatEventBus": ".habitat_bus:HabitatEventBus",
    "HardenedJanusPersistentStateV09": ".live_cycle:HardenedJanusPersistentStateV09",
    "JanusLiveCycle": ".live_cycle:JanusLiveCycle",
    "LiveCycleLedger": ".live_cycle:LiveCycleLedger",
    "HardenedJanusAckReconciler": ".local_lineage:HardenedJanusAckReconciler",
    "HardenedJanusAuthenticatedAckFinalizer": ".local_lineage:HardenedJanusAuthenticatedAckFinalizer",
    "LegacyJanusPersistentState": ".persistent_state:JanusPersistentState",
    "HearthLedger": ".persistent_state:HearthLedger",
    "V07JanusPersistentState": ".persistent_state_v07:HardenedJanusPersistentState",
    "HardenedJanusPersistentStateV08": ".persistent_state_v08:HardenedJanusPersistentStateV08",
    "JanusTransportBroker": ".transport:JanusTransportBroker",
    "TransportLedger": ".transport:TransportLedger",
    "GitHubRepositoryReader": ".model_fabric:GitHubRepositoryReader",
    "ModelFabricCompiler": ".model_fabric:ModelFabricCompiler",
    "ModelFabricError": ".model_fabric:ModelFabricError",

    # Hardened canonical aliases retained for backwards compatibility.
    "JanusAckReconciler": ".local_lineage:HardenedJanusAckReconciler",
    "JanusAuthenticatedAckFinalizer": ".local_lineage:HardenedJanusAuthenticatedAckFinalizer",
    "JanusPersistentState": ".live_cycle:HardenedJanusPersistentStateV09",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target.split(":", 1)
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    # Cache the resolved symbol exactly as normal eager imports would, while
    # keeping the initial bootstrap import minimal.
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
