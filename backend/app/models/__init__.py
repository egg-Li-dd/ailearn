"""模型聚合入口（建表/导入统一走这里）。"""
from .ai_call_log import AiCallLog
from .ai_channel import AiChannel
from .ai_experiment import AiExperiment, AiExperimentEvent
from .audit import AuditLog
from .background_task import BackgroundTask, TaskEvent
from .chat import Conversation, Message, SedimentSuggestion
from .course import Course, ScheduleException, ScheduleItem, ScheduleTemplate
from .knowledge import KnowledgeNode, MasteryRecord, ReviewQueue
from .memory import CourseMemory
from .quiz import QuizAnswer, QuizQuestion, QuizSession, QuizSessionItem
from .study import StudySession, Task
from .system_log import SystemLog
from .user import User, UserSetting

__all__ = [
    "User",
    "UserSetting",
    "AiChannel",
    "AiCallLog",
    "AiExperiment",
    "AiExperimentEvent",
    "AuditLog",
    "BackgroundTask",
    "TaskEvent",
    "Course",
    "ScheduleItem",
    "ScheduleException",
    "ScheduleTemplate",
    "StudySession",
    "Task",
    "Conversation",
    "Message",
    "SedimentSuggestion",
    "CourseMemory",
    "KnowledgeNode",
    "MasteryRecord",
    "ReviewQueue",
    "QuizQuestion",
    "QuizAnswer",
    "QuizSession",
    "QuizSessionItem",
    "SystemLog",
]
