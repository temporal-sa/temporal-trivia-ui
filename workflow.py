import json
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from temporalio import activity, exceptions
from typing import Optional, List, Dict

@dataclass
class GamesWorkflowInput:
    GameId: int
    State: str
    Players: List[Dict]

@dataclass
class TriviaWorkflowInput:
    GameId: str
    NumberOfPlayers: int
    NumberOfQuestions: int
    AnswerTimeLimit: int
    StartTimeLimit: int
    ResultTimeLimit: int
    Category: Optional[str] = None

@dataclass
class PlayerWorkflowInput:
    GameWorkflowId: int
    Player: str
    NumberOfPlayers: int

@dataclass
class StartGameSignal:
    action: str

@dataclass
class AnswerSignal:
    action: str
    player: str
    question: int
    answer: str  