"""
Enhanced Communication Protocol for A.N.K.I.T.A Agent Coordination.

Provides standardized messaging formats, state sharing, and inter-agent
communication patterns to improve coordination between specialist agents.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import uuid
from datetime import datetime


class MessagePriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class MessageType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    ERROR = "error"
    STATUS_UPDATE = "status_update"


@dataclass
class AgentMessage:
    """Standardized message format for inter-agent communication."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    recipient: str = ""
    message_type: MessageType = MessageType.REQUEST
    priority: MessagePriority = MessagePriority.NORMAL
    content: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for serialization."""
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "message_type": self.message_type.value,
            "priority": self.priority.name,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentMessage':
        """Create message from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            sender=data.get("sender", ""),
            recipient=data.get("recipient", ""),
            message_type=MessageType(data.get("message_type", "request")),
            priority=MessagePriority[data.get("priority", "NORMAL")],
            content=data.get("content", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {})
        )


class AgentCommunicationHub:
    """
    Central hub for inter-agent communication.

    Manages message routing, broadcasting, and state synchronization
    between specialist agents.
    """

    def __init__(self):
        self._message_queue: List[AgentMessage] = []
        self._subscribers: Dict[str, List[str]] = {}  # topic -> list of agent names
        self._agent_states: Dict[str, Dict[str, Any]] = {}

    def send_message(self, message: AgentMessage) -> bool:
        """Send a message to a specific agent."""
        # Add to queue for processing
        self._message_queue.append(message)
        print(f"[CommHub] Message queued: {message.sender} -> {message.recipient} ({message.message_type.value})")
        return True

    def broadcast_message(self, message: AgentMessage, topic: str) -> bool:
        """Broadcast a message to all subscribers of a topic."""
        if topic in self._subscribers:
            for agent_name in self._subscribers[topic]:
                if agent_name != message.sender:  # Don't send back to sender
                    broadcast_msg = AgentMessage(
                        sender=message.sender,
                        recipient=agent_name,
                        message_type=message.message_type,
                        priority=message.priority,
                        content=message.content,
                        correlation_id=message.correlation_id,
                        metadata={"broadcast_topic": topic, **message.metadata}
                    )
                    self._message_queue.append(broadcast_msg)
            print(f"[CommHub] Broadcast message to {len(self._subscribers[topic])} agents on topic '{topic}'")
            return True
        return False

    def subscribe(self, agent_name: str, topic: str) -> bool:
        """Subscribe an agent to a topic for broadcasts."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        if agent_name not in self._subscribers[topic]:
            self._subscribers[topic].append(agent_name)
            print(f"[CommHub] {agent_name} subscribed to topic '{topic}'")
            return True
        return False

    def unsubscribe(self, agent_name: str, topic: str) -> bool:
        """Unsubscribe an agent from a topic."""
        if topic in self._subscribers and agent_name in self._subscribers[topic]:
            self._subscribers[topic].remove(agent_name)
            print(f"[CommHub] {agent_name} unsubscribed from topic '{topic}'")
            return True
        return False

    def update_agent_state(self, agent_name: str, state: Dict[str, Any]) -> None:
        """Update the shared state for an agent."""
        if agent_name not in self._agent_states:
            self._agent_states[agent_name] = {}
        self._agent_states[agent_name].update(state)
        print(f"[CommHub] Updated state for {agent_name}")

    def get_agent_state(self, agent_name: str) -> Dict[str, Any]:
        """Get the current state of an agent."""
        return self._agent_states.get(agent_name, {})

    def get_shared_state(self) -> Dict[str, Dict[str, Any]]:
        """Get the complete shared state of all agents."""
        return self._agent_states.copy()

    def process_messages(self) -> List[AgentMessage]:
        """Process all queued messages and return them for delivery."""
        messages_to_deliver = self._message_queue.copy()
        self._message_queue.clear()
        return messages_to_deliver


# Global communication hub instance
COMMUNICATION_HUB = AgentCommunicationHub()


def send_inter_agent_message(
    sender: str,
    recipient: str,
    content: Dict[str, Any],
    message_type: MessageType = MessageType.REQUEST,
    priority: MessagePriority = MessagePriority.NORMAL,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> AgentMessage:
    """Helper function to send a message between agents."""
    message = AgentMessage(
        sender=sender,
        recipient=recipient,
        message_type=message_type,
        priority=priority,
        content=content,
        correlation_id=correlation_id,
        metadata=metadata or {}
    )

    COMMUNICATION_HUB.send_message(message)
    return message


def broadcast_to_agents(
    sender: str,
    topic: str,
    content: Dict[str, Any],
    message_type: MessageType = MessageType.NOTIFICATION,
    priority: MessagePriority = MessagePriority.NORMAL,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Helper function to broadcast a message to all agents subscribed to a topic."""
    message = AgentMessage(
        sender=sender,
        recipient="",  # Will be set for each subscriber
        message_type=message_type,
        priority=priority,
        content=content,
        metadata=metadata or {}
    )

    return COMMUNICATION_HUB.broadcast_message(message, topic)


class AgentCoordinator:
    """Coordinates complex workflows involving multiple agents."""

    def __init__(self, communication_hub: AgentCommunicationHub):
        self.hub = communication_hub
        self.active_workflows: Dict[str, Dict[str, Any]] = {}

    def initiate_workflow(
        self,
        initiator: str,
        agents: List[str],
        task_description: str,
        expected_outcomes: List[str]
    ) -> str:
        """Initiate a coordinated workflow between multiple agents."""
        workflow_id = str(uuid.uuid4())

        workflow_context = {
            "id": workflow_id,
            "initiator": initiator,
            "participants": agents,
            "task": task_description,
            "expected_outcomes": expected_outcomes,
            "status": "initiated",
            "created_at": datetime.now(),
            "steps_completed": [],
            "results": {}
        }

        self.active_workflows[workflow_id] = workflow_context

        # Notify all participants about the workflow
        for agent in agents:
            notification = AgentMessage(
                sender="Coordinator",
                recipient=agent,
                message_type=MessageType.NOTIFICATION,
                priority=MessagePriority.HIGH,
                content={
                    "workflow_id": workflow_id,
                    "action": "workflow_initiated",
                    "task": task_description,
                    "coordinator_instructions": "Please prepare to participate in this coordinated workflow"
                },
                metadata={"workflow_context": workflow_context}
            )
            self.hub.send_message(notification)

        print(f"[Coordinator] Workflow initiated: {workflow_id} by {initiator}")
        return workflow_id

    def update_workflow_status(
        self,
        workflow_id: str,
        agent: str,
        step: str,
        status: str,
        result: Optional[Any] = None
    ) -> bool:
        """Update the status of a workflow step."""
        if workflow_id not in self.active_workflows:
            return False

        workflow = self.active_workflows[workflow_id]
        step_key = f"{agent}:{step}"

        workflow["steps_completed"].append({
            "agent": agent,
            "step": step,
            "status": status,
            "result": result,
            "completed_at": datetime.now()
        })

        if result is not None:
            if "results" not in workflow:
                workflow["results"] = {}
            workflow["results"][step_key] = result

        # Check if workflow is complete
        completed_steps = len(workflow["steps_completed"])
        expected_steps = len(workflow.get("expected_outcomes", []))

        if completed_steps >= expected_steps:
            workflow["status"] = "completed"
            self._notify_workflow_completion(workflow_id)

        return True

    def _notify_workflow_completion(self, workflow_id: str) -> None:
        """Notify the initiator that a workflow is complete."""
        if workflow_id in self.active_workflows:
            workflow = self.active_workflows[workflow_id]
            completion_message = AgentMessage(
                sender="Coordinator",
                recipient=workflow["initiator"],
                message_type=MessageType.STATUS_UPDATE,
                priority=MessagePriority.HIGH,
                content={
                    "workflow_id": workflow_id,
                    "status": "completed",
                    "results": workflow.get("results", {}),
                    "summary": f"Workflow '{workflow['task']}' completed with {len(workflow['steps_completed'])} steps"
                }
            )
            self.hub.send_message(completion_message)
            print(f"[Coordinator] Workflow completed: {workflow_id}")


# Global coordinator instance
COORDINATOR = AgentCoordinator(COMMUNICATION_HUB)