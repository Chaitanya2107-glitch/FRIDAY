"""Loopback-only configuration CRUD for the native customization window."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services import customization
from services.automation.system_control import AutomationError

Section = Literal['contacts', 'routines', 'projects', 'modes', 'screen_apps']


def local_only(request: Request, response: Response):
    if request.client is None or request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
        raise HTTPException(403, 'Customization is available on this computer only.')
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/customization', dependencies=[Depends(local_only)])


class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    original: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    value: customization.Contact | customization.Routine | customization.Mode | customization.Project | customization.ScreenApp


class Delete(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    name: str = Field(min_length=1, max_length=100)


class ModelSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["on", "off"]


class StatusReportSetting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    time: str = Field(max_length=5)


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except customization.Conflict as error:
        raise HTTPException(409, str(error)) from error
    except (customization.StoreUnavailable, OSError, AutomationError) as error:
        raise HTTPException(503, 'Settings could not be loaded or saved. The saved file has been preserved.') from error
    except ValidationError as error:
        raise HTTPException(400, 'Check the fields and value types for this tab.') from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get('/model')
def model_setting():
    from core.config import config
    return {"mode": config.FRIDAY_LLM}


@router.put('/model')
def write_model_setting(body: ModelSetting):
    from providers.failover import set_mode
    return {"mode": call(set_mode, body.mode)}


@router.get('/status-report')
def status_report_setting():
    from services.health.report import report_time
    return {"time": call(report_time)}


@router.put('/status-report')
def write_status_report_setting(body: StatusReportSetting):
    from services.health.report import set_report_time
    return {"time": call(set_report_time, body.time)}


@router.get('/{section}')
def read(section: Section):
    return call(customization.snapshot, section)


@router.put('/{section}')
def save(section: Section, body: Edit):
    return call(customization.change, section, original=body.original, name=body.name,
                value=body.value.model_dump(), revision=body.revision)


@router.delete('/{section}')
def delete(section: Section, body: Delete):
    return call(customization.change, section, original=body.name, name=body.name,
                value=None, revision=body.revision)
