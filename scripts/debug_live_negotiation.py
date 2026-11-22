# coding: utf-8
"""Run one real Live demo phase in an isolated DB and preserve its public evidence.
Usage: .venv/bin/python scripts/debug_live_negotiation.py --demo demo5_release --rounds 15
Human confirmation is automated only for this isolated validation run.
"""
from pathlib import Path
import sys,os,json,argparse
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['PLANBEE_LLM']='live'
os.environ['PLANBEE_RUN_ORIGIN']='debug_live'
from sqlalchemy import select
from app import store,hive,llm,workflow
from app.models import Run,Rule


class StrictLive(llm.LiveLLM):
    def _ask(self,*args,**kwargs):
        answer=super()._ask(*args,**kwargs)
        print(json.dumps(dict(call=self.calls,schema=args[0].__name__,
            action=getattr(answer,'action',getattr(answer,'type',None)),
            error=self.last_error),ensure_ascii=False),flush=True)
        if answer is None and self.last_error and self.last_error['type'] in ('ConnectError','ReadTimeout','ConnectTimeout','HTTPStatusError'):
            raise RuntimeError('Live transport unavailable: '+json.dumps(self.last_error))
        return answer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',default='demo5_release',choices=store.demos())
    parser.add_argument('--rounds',type=int,default=15)
    parser.add_argument('--model',help='Comparison model for this isolated run only; leaves application defaults unchanged')
    parser.add_argument('--all-phases',action='store_true',help='Run every demo feed; stop when PM review is required')
    args=parser.parse_args()
    if args.model:os.environ['PLANBEE_MODEL']=args.model
    store.use_demo(args.demo)
    adapter=StrictLive();llm.set_llm(adapter)
    engine=store.make_engine('sqlite://')
    with store.make_session_factory(engine)() as db:
        store.reset(db)
        db.get(Rule,'rounds').value={'max':args.rounds}
        before=set(store.board(db).tasks)
        error=None
        phases=[]
        try:
            feeds=store.load_yaml('feed.yaml')
            for _ in range(len(feeds)):
                phase=store.meta(db,'phase')
                if phase not in feeds:break
                feed=feeds[phase]
                store.set_meta(db,'now',feed['now'])
                workflow.start_records(db,feed['records'],True,phase_after=feed['next_phase'])
                phases.append(dict(phase=phase,now=feed['now'],next=store.meta(db,'phase')))
                if not args.all_phases or any(r.status in ('waiting_pm','waiting_confirm') for r in db.scalars(select(Run))):break
        except RuntimeError as exc:
            error=str(exc)
            for run in db.scalars(select(Run)):
                run.status='blocked';run.step='done'
                store.hive_say(db,'Live 검증 중단 · '+error,run_id=run.id)
        db.flush()
        b=store.board(db);hive.schedule(b)
        runs=list(db.scalars(select(Run)))
        result=dict(demo=args.demo,model=adapter.model,calls=adapter.calls,failures=adapter.failures,error=error,phases=phases,
            gate=hive.gate(b),
            runs=[dict(id=r.id,status=r.status,round=r.ctx.get('round'),file=r.ctx.get('transcript_file'),
                agreement=[s.get('termination') for s in r.ctx.get('discussion_archive',[])]+[(r.ctx.get('discussion') or {}).get('termination')]) for r in runs],
            new_tasks=[dict(id=t.id,who=t.who,title=t.title,days=t.d,start=t.s,end=t.s+t.d) for t in b.tasks.values() if t.id not in before],
            changed_sources=[dict(id=t.id,who=t.who,days=t.d,kind=t.kind) for t in b.tasks.values() if (t.context or {}).get('completion_barrier')])
        db.commit()
    stamp=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d_%H-%M-%S')
    target=store.ROOT/'eval/live_debug'/f'{stamp}_{args.demo}.json';target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    if error:sys.exit(2)


if __name__=='__main__':main()
