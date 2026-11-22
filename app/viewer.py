"""Local role-experience guard. The selected header is not account authentication.

Omitted headers retain compatibility with existing internal/legacy clients.
"""
from fastapi import HTTPException


def role(request):
    value=request.headers.get('X-Planbee-Role')
    if value is None:return None
    if value=='pm' or value.startswith('person:') and len(value)>7:return value
    raise HTTPException(400,'역할 형식이 잘못되었습니다')


def pm(request):
    if role(request) not in (None,'pm'):raise HTTPException(403,'PM 역할로 전환한 뒤 최종 결정하세요')


def owner(request,pid,allow_pm=True):
    allowed=(None,'person:'+pid,'pm') if allow_pm else (None,'person:'+pid)
    if role(request) not in allowed:raise HTTPException(403,f'{pid} 본인 역할로 전환하세요')
