"""HTTP contracts for the IDE intelligence provider."""

from typing import List, Optional

try:
    import pydantic.v1 as pydantic
    from pydantic.v1 import BaseModel, Field, conint, constr, root_validator
except ImportError:
    import pydantic
    from pydantic import BaseModel, Field, conint, constr, root_validator


def _pattern(value):
    """Keep the standalone service importable with Pydantic 1 and 2."""
    return {"regex": value} if pydantic.VERSION.split(".", 1)[0] == "1" else {"pattern": value}


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class IdeContext(StrictModel):
    type: conint(ge=0, le=2)
    bizId: Optional[constr(min_length=1, max_length=64)] = None
    problemCode: Optional[constr(min_length=1, max_length=128)] = None
    groupIndex: Optional[conint(ge=0, le=100000)] = None
    problemIndex: Optional[conint(ge=0, le=100000)] = None


class CreateSessionRequest(StrictModel):
    protocolVersion: conint(ge=1, le=10)
    clientSessionKey: constr(min_length=16, max_length=256)
    language: constr(**_pattern(r"^(c|cpp|java|python)$"))
    problemCode: Optional[constr(min_length=1, max_length=128)] = None
    judgeTemplateId: Optional[constr(min_length=1, max_length=64)] = None
    context: IdeContext
    code: str = Field(..., max_length=1048576)
    documentName: Optional[constr(min_length=1, max_length=64)] = None


class TextEdit(StrictModel):
    startLine: conint(ge=1)
    startColumn: conint(ge=1)
    endLine: conint(ge=1)
    endColumn: conint(ge=1)
    text: str = Field(..., max_length=1048576)


class SyncRequest(StrictModel):
    baseRevision: conint(ge=1)
    revision: conint(ge=1)
    code: Optional[str] = Field(None, max_length=1048576)
    edits: Optional[List[TextEdit]] = None

    @root_validator(skip_on_failure=True)
    def one_sync_form(cls, values):
        code, edits = values.get("code"), values.get("edits")
        if (code is None) == (edits is None):
            raise ValueError("Provide exactly one of code or edits")
        if edits is not None and len(edits) > 256:
            raise ValueError("Too many edits")
        return values


class PositionRequest(StrictModel):
    revision: conint(ge=1)
    line: conint(ge=1)
    column: conint(ge=1)
    triggerKind: Optional[constr(**_pattern(r"^(invoked|triggerCharacter|triggerForIncompleteCompletions)$"))] = None
    triggerCharacter: Optional[constr(max_length=8)] = None


class DiagnosticsRequest(StrictModel):
    revision: conint(ge=1)
