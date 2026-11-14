from pydantic import BaseModel

class Incident(BaseModel):
    call_type: str
    weapon_present: bool | None = None
    injury: bool | None = None
    violence: bool | None = None

    