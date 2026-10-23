"""Bounded large-book outlines using source groups with complete source retention."""
import json
from pydantic import Field
from .schemas import StrictModel
from .providers import parse_json
from .deep import representative_sources


class GroupSection(StrictModel):
    title: str=Field(min_length=1,max_length=250)
    parent_index: int | None=None
    group_ids: list[int]=Field(min_length=1)


class GroupOutline(StrictModel):
    name: str=Field(min_length=1,max_length=120)
    sections: list[GroupSection]=Field(min_length=1,max_length=200)


def propose_grouped(research,book_id,request,settings):
    from .research import prompt
    sources=research.library.passages(book_id)
    instruction=prompt('group_structure')
    budget=settings.input_chars-len(instruction)-len(request)-1024
    if budget<2500:raise ValueError('The requested structure leaves too little input space. Shorten the instruction or increase the input budget.')
    count=min(len(sources),64,max(1,budget//700))
    groups=[];mapping={}
    for i in range(count):
        group=sources[i*len(sources)//count:(i+1)*len(sources)//count]
        mapping[i]=[p['id'] for p in group]
        groups.append({'group_id':i,'pdf_pages':sorted({p['page'] for p in group}),
            'samples':[{'page':p['page'],'text':p['text'][:180]} for p in representative_sources(group,2)]})
    body=json.dumps({'request':request,'source_groups':groups},ensure_ascii=False)
    if len(body)+len(instruction)>settings.input_chars:
        raise ValueError('Grouped outline still exceeds the input budget. Increase the input limit for this model.')
    output=GroupOutline.model_validate(parse_json(research.provider_factory(settings).complete(instruction,[{'role':'user','content':body}])))
    sections=[]
    for section in output.sections:
        if any(g not in mapping for g in section.group_ids):raise ValueError('The outline referenced an unknown source group')
        ids=list(dict.fromkeys(pid for g in section.group_ids for pid in mapping[g]))
        sections.append({'title':section.title,'parent_index':section.parent_index,'source_ids':ids})
    return research.save_structure(book_id,{'name':output.name,'sections':sections},origin='Grouped source preview; verify thematic boundaries')
