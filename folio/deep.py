"""Bounded, checkpointed deep reading and source-grounded reading previews."""
import hashlib
import json
import re
from typing import Literal
from pydantic import Field
from .db import uid, now
from .schemas import StrictModel, Finding
from .providers import parse_json, ProviderError


class SourceReview(StrictModel):
    source_id: str
    status: Literal['substantive', 'reference', 'navigation', 'unclear', 'outside_focus']
    reason: str = Field(min_length=1, max_length=600)


class DeepExtraction(StrictModel):
    findings: list[Finding] = Field(max_length=40)
    reviews: list[SourceReview] = Field(min_length=1, max_length=12)


def compact_source(p):
    return {k: p[k] for k in ('id','page','label','text')}


def source_weight(p):
    """Prefer explanatory prose for previews, without excluding any source from deep reading."""
    text = p['text']; words = text.split()
    weight = min(len(words), 160)
    if len(words) < 18: weight -= 150
    if re.search(r'(?i)retrieved from|accessed.*20\d\d|https?://|doi\b', text): weight -= 100
    if text.count('…') > 3 or text.count(' . ') > 3: weight -= 100
    return weight


def representative_sources(passages, limit=8):
    if len(passages) <= limit: return sorted(passages, key=source_weight, reverse=True)
    # Sample across the scope, prefer substantive prose within each interval.
    result=[]
    for index in range(limit):
        chunk=passages[index*len(passages)//limit:(index+1)*len(passages)//limit]
        if chunk: result.append(max(chunk, key=source_weight))
    return result


class DeepResearch:
    def deep_payload(self, book_id, section_ids=None, focus=''):
        payload = self.extraction_payload(book_id, section_ids, focus)
        payload['mode']='deep'; payload['reader_version']=1
        return payload

    def deep_batches(self, book_id, source_ids, focus, settings):
        from .research import prompt
        instruction = prompt('deep_extract')
        book = self.library.book(book_id)
        base = {'title':book['title'], 'focus':focus, 'sources':[]}
        budget = min(7500, settings.input_chars - len(instruction) - len(json.dumps(base,ensure_ascii=False)) - 256)
        if budget < 2500: raise ValueError('The instruction and focus leave too little space for sources. Shorten the focus or increase the input limit.')
        batch=[]; size=0
        for pid in source_ids:
            source=compact_source(self.library.source(book_id,pid))
            length=len(json.dumps(source,ensure_ascii=False))+2
            if length > budget: raise ValueError('A passage exceeds the input budget; increase the input limit.')
            if batch and (size+length>budget or len(batch)>=12):
                yield {**base,'sources':batch}; batch=[]; size=0
            batch.append(source);size+=length
        if batch: yield {**base,'sources':batch}

    def run_deep(self, job, cancelled):
        from .research import prompt
        payload=json.loads(job['payload']); settings=self.config.get(payload['provider'])
        if settings.model!=payload['model'] or settings.endpoint!=payload['endpoint']:
            raise ValueError('Provider settings changed since this job was created. Restore them to resume, or start a new deep reading.')
        pending={r['passage_id'] for r in self.db.rows("SELECT passage_id FROM job_units WHERE job_id=? AND status!='done'",(job['id'],))}
        ordered=[pid for pid in payload['source_ids'] if pid in pending]
        instruction=prompt('deep_extract'); version=hashlib.sha256(instruction.encode()).hexdigest()[:12]
        provider=self.provider_factory(settings)
        for body in self.deep_batches(job['book_id'],ordered,payload['focus'],settings):
            if cancelled(): raise InterruptedError('Deep reading cancelled; completed batches are saved')
            sources={p['id']:p for p in body['sources']}
            try:
                # One automatic retry for malformed or unverifiable output; provider errors (keys, limits) stop at once.
                for attempt in range(2):
                    try:
                        output=self.deep_batch_output(provider,instruction,body,sources)
                        break
                    except ProviderError: raise
                    except ValueError:
                        if attempt or cancelled(): raise
                if cancelled(): raise InterruptedError('Deep reading cancelled; completed batches are saved')
                with self.db.connect() as db:
                    for f in output.findings:
                        db.execute('INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid(),job['id'],job['book_id'],f.category,f.title,f.content,json.dumps(f.details,ensure_ascii=False),json.dumps([e.model_dump() for e in f.evidence],ensure_ascii=False),settings.provider,settings.model,version,now()))
                    for review in output.reviews:
                        db.execute('INSERT OR REPLACE INTO deep_reviews VALUES(?,?,?,?,?)',(job['id'],review.source_id,review.status,review.reason,now()))
                        db.execute("UPDATE job_units SET status='done',error=NULL WHERE job_id=? AND passage_id=?",(job['id'],review.source_id))
                    count=db.execute("SELECT count(*) FROM job_units WHERE job_id=? AND status='done'",(job['id'],)).fetchone()[0]
                    db.execute('UPDATE jobs SET completed=?,updated=? WHERE id=?',(count,now(),job['id']))
            except InterruptedError: raise
            except Exception as exc:
                message='Invalid structured deep-reading response' if type(exc).__module__.startswith('pydantic') else str(exc)
                with self.db.connect() as db:
                    for pid in sources: db.execute("UPDATE job_units SET status='failed',error=? WHERE job_id=? AND passage_id=?",(message,job['id'],pid))
                raise ValueError(message+'. Completed batches remain saved; resume to retry.') from None

    def deep_batch_output(self, provider, instruction, body, sources):
        from .research import normalized
        raw=provider.complete(instruction,[{'role':'user','content':json.dumps(body,ensure_ascii=False)}],json_mode=True)
        output=DeepExtraction.model_validate(parse_json(raw))
        reviewed=[r.source_id for r in output.reviews]
        if len(set(reviewed))!=len(reviewed) or set(reviewed)!=set(sources):
            raise ValueError('The model did not account for every supplied passage; batch needs retry')
        cited=set()
        for f in output.findings:
            for evidence in f.evidence:
                if evidence.source_id not in sources or normalized(evidence.quote) not in normalized(sources[evidence.source_id]['text']):
                    raise ValueError('A finding contains an invalid source or quotation; batch needs retry')
                cited.add(evidence.source_id)
        if any(r.status=='substantive' and r.source_id not in cited for r in output.reviews):
            raise ValueError('A substantive passage was marked read without a finding; batch needs retry')
        return output

    def reading_overview(self, book_id, section_id=None):
        passages=self.library.passages(book_id,section_id); ids={p['id'] for p in passages}
        done={r['passage_id'] for r in self.db.rows("SELECT DISTINCT u.passage_id FROM job_units u JOIN jobs j ON j.id=u.job_id WHERE j.book_id=? AND u.status='done'",(book_id,))}
        findings=self.findings(book_id,section_id)
        reviews=self.db.rows('SELECT r.* FROM deep_reviews r JOIN jobs j ON j.id=r.job_id WHERE j.book_id=? ORDER BY r.created DESC',(book_id,))
        reasons={}
        for r in reviews:
            if r['passage_id'] in ids and r['passage_id'] not in reasons: reasons[r['passage_id']]=r
        return {'passages':len(passages), 'pages':len({p['page'] for p in passages}),
                'reviewed':len(ids & done), 'findings':len(findings),
                'excerpts':representative_sources(passages),
                'skipped':sum(r['status']!='substantive' for r in reasons.values()),
                'reviews':list(reasons.values())}


def initial_evidence(library, book_id, question, section_id, source_id, budget):
    passages=library.passages(book_id,section_id)
    selected=[library.source(book_id,source_id)] if source_id else []
    if selected:
        chosen=selected[0]
        candidates=selected+[p for p in passages if p['page']==chosen['page'] and p['id']!=chosen['id']]
    else:
        stop={'what','are','the','is','this','book','section','please','explain','give','me','tell','about','more','detail','detailed','information','main','ideas','of','in','and','a','an','to','it','can','you','all'}
        query=' '.join(w for w in re.findall(r'\w+',question.casefold()) if w not in stop)
        matches=library.search(book_id,query,section_id,limit=24) if query else []
        matches=sorted(matches,key=lambda p:source_weight(p),reverse=True)
        # Supply actual neighboring fragments as well as matches, maintaining scope.
        neighbors=[]; by_id={p['id']:i for i,p in enumerate(passages)}
        for p in matches[:4]:
            pos=by_id[p['id']];neighbors.extend(passages[max(0,pos-1):pos+2])
        candidates=matches[:4]+neighbors+representative_sources(passages,8)
    result=[];seen=set();size=2
    for source in candidates:
        if source['id'] in seen: continue
        item=compact_source(source);length=len(json.dumps(item,ensure_ascii=False))+2
        if size+length > budget: continue
        result.append(item);seen.add(source['id']);size+=length
        if len(result)>=14:break
    return result
