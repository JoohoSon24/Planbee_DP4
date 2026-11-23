"""Display-only translation of public run text; never alters negotiations or cards."""
from collections import OrderedDict
from threading import Lock
from types import SimpleNamespace
import re
from pydantic import BaseModel, Field
from . import prompts
from .llm import LiveLLM, get_llm
from .negotiation_budget import bound, CallBudgetExceeded

class Translation(BaseModel):
    id: str
    text: str = Field(min_length=1)

class TranslationBatch(BaseModel):
    translations: list[Translation]

_cache=OrderedDict()
_attempts=OrderedDict()
_lock=Lock()


def public_texts(run):
    items={'issue':run.ctx['issue']}
    if run.ctx.get('clarification'):items['clarification']=run.ctx['clarification']
    items.update({f'history:{i}':e['reason'] for i,e in enumerate(run.ctx.get('public_history',[])) if e.get('reason')})
    return items


def translate(run,keys,*,limit=32):
    sources=public_texts(run)
    if len(keys)!=len(set(keys)) or any(k not in sources for k in keys):raise ValueError('Unknown or duplicate public message reference')
    if sum(len(sources[k]) for k in keys)>12000:raise ValueError('Translation batch exceeds 12000 characters')
    # Serialise display translation requests so language toggles cannot duplicate billing.
    with _lock:
        missing=[k for k in keys if sources[k] not in _cache]
        if missing:
            adapter=get_llm()
            if not isinstance(adapter,LiveLLM):raise ValueError('English translation requires Live mode; Mock does not make paid translation calls.')
            if type(adapter) is LiveLLM:
                original=adapter
                adapter=LiveLLM(client=original.client)
                adapter.key=original.key;adapter.model=original.model
            count=_attempts.get(run.id,0)
            if count>=limit:raise ValueError('Display translation call limit reached for this run')
            _attempts[run.id]=count+1;_attempts.move_to_end(run.id)
            while len(_attempts)>128:_attempts.popitem(last=False)
            try:
                with bound(dict(used=0,max=3)):
                    answer=adapter._ask(TranslationBatch,prompts.load_prompt('translation','english'),
                        dict(target_language='en',messages=[dict(id=k,text=sources[k]) for k in missing]))
            except CallBudgetExceeded as exc:raise ValueError('Translation request limit reached') from exc
            if answer is None:raise ValueError('Translation model unavailable; retry from the English view.')
            ids=[x.id for x in answer.translations]
            if len(ids)!=len(missing) or set(ids)!=set(missing):raise ValueError('Translation returned invalid message references')
            if any(re.search('[가-힣]',item.text) for item in answer.translations):raise ValueError('Translation must contain English only')
            for item in answer.translations:
                _cache[sources[item.id]]=item.text;_cache.move_to_end(sources[item.id])
            while len(_cache)>2000:_cache.popitem(last=False)
        return dict(language='en',items=[dict(id=k,source=sources[k],text=_cache[sources[k]]) for k in keys])



def translate_display(texts):
    if len(set(texts))!=len(texts):raise ValueError('Duplicate display text')
    if sum(map(len,texts))>12000:raise ValueError('Translation batch exceeds 12000 characters')
    # Display text is submitted by the local viewer, never read from other cards.
    # It is not stored in runs or negotiation state.
    run=SimpleNamespace(id='display',ctx={'issue':'','public_history':[{'reason':x} for x in texts]})
    result=translate(run,[f'history:{i}' for i in range(len(texts))],limit=128)
    return {'items':[{'source':x['source'],'text':x['text']} for x in result['items']]}
