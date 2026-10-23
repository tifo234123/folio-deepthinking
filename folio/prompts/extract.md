# Structured extraction
Extract useful information only from the supplied sources. A source may be a fragment; do not complete it from memory. The optional focus narrows the research objective. Return an empty findings list for irrelevant material, repeated page headers, navigation text, or content lacking substantive information.

Output exactly:
{"findings":[{"category":"main|definition|formula|method|data","title":"Short title","content":"The grounded finding, preserving conditions and uncertainty","details":{"optional field":"string value"},"evidence":[{"source_id":"an exact supplied id","quote":"a verbatim contiguous excerpt of at least 3 characters"}]}]}

Each finding needs at least one source. Quotes must occur verbatim in that source apart from whitespace normalization. Use the smallest sufficient quote. Do not invent missing content. No fields outside this schema. Maximum 40 findings per response; favor a small number of substantive findings.

Category guidance:
- main: claims, arguments, findings, relationships, explanations, qualifications.
- definition: a term and its explicit definition. Mark contextual interpretations as inferred in details.
- formula: mathematical expression with stated symbol meanings, units, conditions, and uncertainty. Use details keys formula, symbols, units, conditions, uncertainty when applicable.
- method: purpose, ordered steps, stated inputs and conditions, limitations.
- data: values together with labels, units, table relationships and experimental context. Mark ambiguous column alignment for original-page review.

Example shape for missing definitions:
{"findings":[{"category":"formula","title":"Discharge equation","content":"The passage gives Q = A v. Symbol definitions are not included in this excerpt.","details":{"formula":"Q = A v","symbols":"Not defined in the supplied passage","uncertainty":"Verify notation on the original PDF page"},"evidence":[{"source_id":"SUPPLIED_ID","quote":"Q = A v"}]}]}
Never use the literal example source ID unless it actually appears in the input.

