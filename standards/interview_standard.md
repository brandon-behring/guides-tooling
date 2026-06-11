# Interview Standard

Fleet-wide contract for interview preparation content. Required at
chapter, appendix, and guide-level.

## Chapter-level requirements

Every authored chapter (excluding `00_how_to_use`) must include:

- `\companytags{...}` on the chapter — role/company/level metadata. Even when
  empty, the macro must be present so audits don't flag the chapter as
  unmapped.
- At least one `\interviewmargin{}` per chapter when interview material
  applies. See [`content_design.md`](content_design.md) for craft rules.
- A `\begin{interviewcontext}[Title][LOS]...\end{interviewcontext}` box when
  the topic maps to a common interview competency. Not every chapter needs
  one (e.g., environment-setup chapters), but most do.

## Guide-level requirements

Every guide must include:

### Appendix D — `D_interview_prep.tex`

Required for every guide. A stub Appendix D **fails Silver tier** (per
[`tier_model.md`](tier_model.md)).

Content requirements:

- **At least 5 conceptual questions** with expected-answer points (not just
  question prompts).
- **At least 1 system / design scenario** when the topic supports it.
  System-design questions are essential for Staff+ candidates.
- **Follow-up questions** — interviewers go deeper; candidates must too.
- **Role / level expectations** — explicit IC3/IC4 vs IC5+/Staff deltas.
  An IC4 should be able to do X; an IC5 should additionally be able to do Y.
- **Cross-references back to chapters** via LOS IDs (`Chapter 5,
  TRB-5.2`).
- **Company / role framing** — likely interview contexts (FAANG vs scale-up
  vs research lab, individual contributor vs managerial track).

For non-ML/AI books, Appendix D maps the material to relevant engineering,
design, architecture, testing, data, or behavioral interview signals.
Examples:

- A Python testing book → behavioral signals about test discipline; design
  questions about test pyramid; system questions about CI/CD.
- A docker book → infra interview signals; design questions about
  containerization tradeoffs.

### `review/interview_connections.md`

Required for every guide. **A stub file fails Silver tier.**

Format (loose; the exemplar is below):

```markdown
# Interview Connections: [Course Name]

**Course ID**: [ID]
**Sprint**: [N]  |  **Phase**: [N]

## Question Mapping
[Map specific interview questions to chapters/LOS]

## Volume Cross-References
[Map to other guides in the learning graph]

## Gaps Addressed / Portfolio Connection
[How this guide closes a portfolio or interview-prep gap]
```

**Exemplar**: `llms-and-transformers/manning_llm_from_scratch/review/interview_connections.md` —
4 mapped interview questions (Q5/Q6/Q8/Q12) with detailed connections to
companion volumes and talking points.

**Stub examples to avoid**:
- "No direct mapping to specific interview questions" — too generic; doesn't
  help anyone preparing.
- Empty section bodies under populated headers.

## Interview-prep authoring cost

The fleet is all-Manning, but books vary in how much interview material is
extractable, which drives Appendix D and `interview_connections.md` cost:

| Source shape | Source for interview material | Authoring cost |
|--------------|-------------------------------|----------------|
| Book with explicit Q&A / test-yourself content | Often extractable from book content (some books have explicit Q&A appendices); supplement books may carry drills | Lower (extract + polish) |
| Book without dedicated interview material | Synthesized from chapter content | Medium (synthesize from prose + worked examples) |
| Broad-survey / multi-topic book | **Mostly authored** — little ready-made Q&A to extract | High (must author across the book's breadth) |

Broad-survey guides therefore have the highest Appendix-D authoring cost
relative to source size; budget accordingly.

## What "interview-ready" means at each tier

- **Bronze**: Appendix D file exists. May be a stub.
- **Silver**: Appendix D is real (5+ questions with expected-answer points,
  1+ system/design scenario, role/level deltas, LOS cross-refs).
  `interview_connections.md` is real (not a stub).
- **Gold**: Silver plus interview cards (`\begin{interviewcontext}` boxes
  extracted to cards) cover material across multiple chapters; chapter-level
  `\companytags` are populated; `\interviewmargin{}` notes appear at the
  designed density (not just a few token notes).

## Cross-reference

For cross-guide interview-prep coordination (which guide owns which
interview competency), see [`cross_references.md`](cross_references.md).

For role/level vocabulary used in margin notes, follow
[`content_design.md`](content_design.md) per-category craft for `[Interview]`
notes.
