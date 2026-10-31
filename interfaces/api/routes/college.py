"""Thin loopback college routes with a consistent error envelope."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from core.errors import ProviderError, _error_response
from services.automation.system_control import AutomationError
from services.college import models, overview, parsers, schedules, service, store, uploads

Section = Literal['timetable', 'subjects', 'deadlines', 'exams', 'events']


class CollegeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handle(request):
            try:
                return await original(request)
            except (RequestValidationError, ValidationError) as error:
                fields = error.errors()
                message = '; '.join('.'.join(str(p) for p in f['loc']) + ': ' + f['msg'] for f in fields[:5])
                return _error_response('validation_error', message, 422)
            except store.Conflict as error:
                return _error_response('conflict', str(error), 409)
            except (store.Unavailable, AutomationError, OSError, sqlite3.Error) as error:
                return _error_response('store_unavailable', 'College data could not be loaded or saved. Check the current catalog before retrying; repair unreadable files.', 503)
            except ProviderError as error:
                return _error_response('provider_error', str(error), 502)
            except HTTPException as error:
                return _error_response('request_error', str(error.detail), error.status_code)
            except ValueError as error:
                return _error_response('validation_error', str(error), 400)
        return handle


def local_only(request: Request, response: Response):
    if request.client is None or request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
        raise HTTPException(403, 'College Schedules is available on this laptop only.')
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/college', dependencies=[Depends(local_only)], route_class=CollegeRoute)


@router.get('/overview')
def home():
    return overview.overview()


@router.post('/timetable/date')
def move_date(body: models.DatedMove):
    return schedules.move_date(body)


@router.get('/uploads')
def list_uploads():
    return uploads.listing()


@router.get('/uploads/vision')
def vision():
    return uploads.vision()


@router.post('/uploads')
async def upload(request: Request, filename: str = Query(min_length=1, max_length=160)):
    parsers.filename(filename)
    content_length = request.headers.get('content-length')
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError:
            raise HTTPException(400, 'Invalid Content-Length.') from None
        if length < 0 or length > parsers.MAX_BYTES:
            raise HTTPException(413, 'Choose a file no larger than 10 MB.')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > parsers.MAX_BYTES:
            raise HTTPException(413, 'Choose a file no larger than 10 MB.')
        body.extend(chunk)
    return await run_in_threadpool(uploads.stage, filename, bytes(body))


@router.post('/uploads/{token}/extract')
async def extract(token: str, body: models.Consent):
    return await uploads.extract(token, body.consent, body.section)


@router.post('/uploads/{token}/preview')
def preview(token: str, body: models.ImportEdit):
    return uploads.preview(token, body)


@router.post('/uploads/{token}/confirm')
def confirm(token: str, body: models.Confirm):
    return uploads.confirm(token, body)


@router.delete('/uploads/{token}/preview')
def discard(token: str):
    return uploads.discard(token)


@router.delete('/uploads/{identifier}')
def delete_upload(identifier: str, body: models.Delete):
    if identifier != body.id:
        raise ValueError('Upload identifier does not match the selected file.')
    return uploads.delete(identifier, body.revision)


@router.get('/{section}')
def read(section: Section, day: str | None = Query(default=None, alias='date')):
    return service.snapshot(section, day)


@router.put('/{section}')
def save(section: Section, body: models.Edit):
    return service.change(section, body.id, body.value, body.revision)


@router.delete('/{section}')
def delete(section: Section, body: models.Delete):
    return service.change(section, body.id, None, body.revision)
