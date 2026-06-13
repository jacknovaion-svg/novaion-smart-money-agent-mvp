import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.system_log import SystemLog


def write_log(
    db: Session,
    *,
    level: str,
    module: str,
    message: str,
    payload: Optional[Dict[str, Any]] = None,
) -> SystemLog:
    log = SystemLog(
        level=level.upper(),
        module=module,
        message=message,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
