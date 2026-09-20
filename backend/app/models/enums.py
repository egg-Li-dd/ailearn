"""枚举常量（单点定义，DB 中以字符串存储）。"""


class SessionStatus:
    SCHEDULED = "scheduled"
    PRE_CLASS = "pre_class"
    IN_CLASS = "in_class"
    REVIEW = "review"
    DONE = "done"
    OVERDUE = "overdue"


class TaskStatus:
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    SKIPPED = "skipped"


class TaskType:
    READ = "read"
    PRACTICE = "practice"
    MEMORY = "memory"
    THINK = "think"
    REVIEW = "review"


class SedimentKind:
    CONCEPT = "concept"
    CORRECTION = "correction"
    CONCLUSION = "conclusion"


class SedimentStatus:
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Source:
    MANUAL = "manual"
    QA_SEDIMENT = "qa_sediment"
    AI_GENERATED = "ai_generated"
    PASTE_OUTLINE = "paste_outline"
    SELF_REPORT = "self_report"


class NodeStatus:
    UNTOUCHED = "untouched"
    LEARNING = "learning"
    MASTERED = "mastered"
    REVIEW = "review"


class ReviewStatus:
    OPEN = "open"
    DONE = "done"


class ScheduleAction:
    ADD = "add"
    REMOVE = "remove"


class MessageRole:
    USER = "user"
    ASSISTANT = "assistant"


class ConversationMode:
    FREE = "free"
    QUIZ = "quiz"
    MINI_TEST = "mini_test"