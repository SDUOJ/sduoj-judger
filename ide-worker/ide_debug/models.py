"""The HTTP interface is a small command protocol, not an arbitrary DAP tunnel."""

from typing import Any, Dict, List, Literal, Optional
try:
    from pydantic.v1 import BaseModel, Field, constr, conint, validator
except ImportError:
    from pydantic import BaseModel, Field, constr, conint, validator
from ide_intelligence.models import IdeContext

Identifier = constr(regex=r"^[A-Za-z0-9_-]{16,80}$")


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class Create(StrictModel):
    commandId: Identifier
    language: constr(regex=r"^(c|cpp|java|python)$")
    judgeTemplateId: constr(regex=r"^[1-9][0-9]{0,18}$")
    problemCode: constr(min_length=1, max_length=128)
    context: IdeContext
    code: constr(min_length=1, max_length=262144)
    input: constr(max_length=65536) = ""
    breakpoints: List[conint(ge=1, le=100000)] = Field(
        default_factory=list, max_items=128
    )
    replaceExisting: bool = False
    restoreOnly: bool = False
    resumeSessionId: Optional[Identifier] = None
    resumeSessionEpoch: Optional[Identifier] = None

    @validator("code", "input")
    def utf8_limits(cls, value, field):
        if "\x00" in value or len(value.encode()) > (
            262144 if field.name == "code" else 65536
        ):
            raise ValueError("Invalid source/input size")
        return value


class Command(StrictModel):
    commandId: Identifier
    sessionEpoch: Identifier
    expectedStateVersion: conint(ge=0)
    stopId: Optional[constr(max_length=80)] = None
    operation: constr(
        regex=r"^(continue|next|stepIn|stepOut|threads|stackTrace|scopes|variables|setBreakpoints|stdin|watch)$"
    )
    arguments: Dict[str, Any] = Field(default_factory=dict)

    @validator("arguments")
    def bounded_arguments(cls, value):
        import json

        if len(json.dumps(value).encode()) > 65536:
            raise ValueError("Arguments too large")
        return value


class Poll(StrictModel):
    cursor: conint(ge=0) = 0
    waitSeconds: conint(ge=0, le=20) = 0


class Control(StrictModel):
    sessionEpoch: Identifier


class Cancel(Control):
    ticketId: Identifier
