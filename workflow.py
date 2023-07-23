import json
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from temporalio import activity, exceptions

@dataclass
class TriviaWorkflowInput:
    NumberOfPlayers: int
    NumberOfQuestions: int

@dataclass
class PlayerWorkflowInput:
    GameWorkflowId: int
    Player: str

@dataclass
class StartGameSignal:
    action: str