# Structure proposal
Return a proposed named outline based on the requested organization and the supplied source descriptors. Descriptors contain short excerpts, not complete passages; do not claim exhaustive thematic interpretation from them. Use only their exact IDs. A section may reference noncontiguous sources. Source IDs may appear in multiple meaningful sections. Preserve every source where possible; the application retains any unmapped material in an additional section.

Output exactly:
{"name":"By treatment method","sections":[{"title":"Sand filtration","parent_index":null,"source_ids":["SUPPLIED_ID"]}]}

parent_index is null for a root or a zero-based index of an earlier parent section. It must never refer to itself or a later section. Sections need at least one source each. Do not output applied/completed claims: this operation only proposes a structure. Original chapters remain available. Use the requested split, merge, title change, or thematic grouping, without inventing source material.

