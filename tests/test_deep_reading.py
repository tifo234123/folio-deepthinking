import json
import pytest
from folio.db import uid
from folio.deep import initial_evidence
from folio.providers import ProviderError


def deep_response(body):
    return {'findings':[{'category':'main','title':'Evidence and conditions','content':p['text'],
        'details':{'context':'Limited to the supplied passage'},'evidence':[{'source_id':p['id'],'quote':p['text']}]} for p in body['sources']],
        'reviews':[{'source_id':p['id'],'status':'substantive','reason':'Supports the extracted explanation'} for p in body['sources']]}


def test_deep_batches_checkpoint_resume_and_evidence(app,book):
    for i in range(20):
        app.db.execute('INSERT INTO passages VALUES(?,?,?,?,?,?,?)',(uid(),book['id'],3,'3',i+10,f'Additional experiment {i} used controlled pressure and measured water flow.','[]'))
    calls=[]
    class Model:
        def __init__(self,settings): self.settings=settings
        def complete(self,system,messages,max_tokens=None,**kwargs):
            assert len(system)+sum(len(m['content']) for m in messages)<=self.settings.input_chars
            body=json.loads(messages[-1]['content']);calls.append(body)
            if len(calls)==2:raise ProviderError('Temporary failure')
            return json.dumps(deep_response(body))
    app.research.provider_factory=Model
    payload=app.research.deep_payload(book['id'])
    job=app.jobs.create(book['id'],'extract',payload,background=False)
    assert job['status']=='failed' and 0<job['completed']<job['total']
    completed=job['completed']; assert len(app.research.findings(book['id']))==completed
    app.jobs.resume(job['id'],background=False)
    assert app.jobs.get(job['id'])['status']=='done'
    findings=app.research.findings(book['id'])
    assert len(findings)==len(payload['source_ids'])
    assert len({f['sources'][0]['source_id'] for f in findings})==len(findings)
    overview=app.research.reading_overview(book['id'])
    assert overview['reviewed']==overview['passages'] and overview['findings']==len(findings)


@pytest.mark.parametrize('fault',['missing_review','invalid_quote','substantive_without_finding'])
def test_deep_rejects_incomplete_or_unverified_output(app,book,fault):
    class Model:
        def __init__(self,settings):pass
        def complete(self,system,messages,max_tokens=None,**kwargs):
            result=deep_response(json.loads(messages[-1]['content']))
            if fault=='missing_review':result['reviews'].pop()
            elif fault=='invalid_quote':result['findings'][0]['evidence'][0]['quote']='Completely fabricated result'
            else:result['findings']=[]
            return json.dumps(result)
    app.research.provider_factory=Model
    job=app.jobs.create(book['id'],'extract',app.research.deep_payload(book['id']),background=False)
    assert job['status']=='failed' and job['completed']==0
    assert not app.research.findings(book['id'])


def test_empty_reference_review_is_explicit(app,book):
    class Model:
        def __init__(self,settings):pass
        def complete(self,system,messages,max_tokens=None,**kwargs):
            sources=json.loads(messages[-1]['content'])['sources']
            return json.dumps({'findings':[],'reviews':[{'source_id':p['id'],'status':'reference','reason':'Test fixture: reference entry only'} for p in sources]})
    app.research.provider_factory=Model
    job=app.jobs.create(book['id'],'extract',app.research.deep_payload(book['id']),background=False)
    assert job['status']=='done'
    view=app.research.reading_overview(book['id']);assert view['skipped']==view['passages'] and view['findings']==0


def test_deep_context_respects_section_and_budget(app,book):
    section=app.library.sections(book['id'])[-1]['id']
    allowed={p['id'] for p in app.library.passages(book['id'],section)}
    sources=initial_evidence(app.library,book['id'],'Explain all of this in detail',section,None,4000)
    assert sources and all(p['id'] in allowed for p in sources)
    assert len(json.dumps(sources,ensure_ascii=False))<=4000


def test_grouped_outline_preserves_all_sources(app,book):
    for i in range(150):
        app.db.execute('INSERT INTO passages VALUES(?,?,?,?,?,?,?)',(uid(),book['id'],i+10,str(i+10),0,'Water and energy systems interact. '+('Detailed supporting evidence. '*35),'[]'))
    class Model:
        def __init__(self,settings):self.settings=settings
        def complete(self,system,messages,max_tokens=None,**kwargs):
            assert len(system)+len(messages[0]['content'])<=self.settings.input_chars
            body=json.loads(messages[0]['content']);assert 'source_groups' in body
            return json.dumps({'name':'Water and energy','sections':[{'title':'Connected systems','group_ids':[0],'parent_index':None}]})
    app.research.provider_factory=Model
    original=app.library.book(book['id'])['active_structure']
    proposal=app.research.propose_structure(book['id'],'Group by topic')
    sections=app.library.sections(book['id'],proposal['structure_id'])
    mapped={p for section in sections for p in section['source_ids']}
    assert mapped=={p['id'] for p in app.library.passages(book['id'])}
    assert app.library.book(book['id'])['active_structure']==original


@pytest.mark.parametrize('bad_attempts,status',[(1,'done'),(2,'failed')])
def test_deep_batch_retries_invalid_output_once(app,book,bad_attempts,status):
    calls=[]
    class Model:
        def __init__(self,settings):pass
        def complete(self,system,messages,max_tokens=None,json_mode=False):
            assert json_mode
            calls.append(1)
            if len(calls)<=bad_attempts:return 'not json at all'
            return 'Here is the result: '+json.dumps(deep_response(json.loads(messages[-1]['content'])))
    app.research.provider_factory=Model
    job=app.jobs.create(book['id'],'extract',app.research.deep_payload(book['id']),background=False)
    assert job['status']==status and len(calls)==2


def test_assistant_extract_requires_confirmation(app,book):
    result=app.assistant._tool('extract',{'scope':'book','focus':'methods'},book['id'],None)
    assert result['total_passages']>0 and result['model_calls']>0 and result['focus']=='methods'
    assert not app.db.rows("SELECT id FROM jobs WHERE kind='extract'")
