# Joint Codebook: Reddit and Interviews

This codebook merges the codes from the 21 practitioner interviews (P1–P21) and the 99 Reddit
records relevant to SDD practice (R1–R99). Each code is named *high-level code: low-level code*.
The machine-readable version is `joint_codebook.csv`.

- 427 low-level codes under 15 high-level codes
- 412 codes appear in the interviews and 174 in the Reddit records; 159 appear in both,
  253 only in the interviews, and 15 only on Reddit
- Tool makers (participants who created and publicly released an SDD tool): P1, P2, P6, P9, P11, P13, P20, P21. All other participants are tool users.

Columns: *Participants* lists the interviewees assigned the code (tool makers in bold);
*Reddit records* lists the Reddit records assigned the code. Within each high-level code, codes
are ordered by the number of participants, then by the number of Reddit records.

## Summary

| High-level code | Low-level codes | Interviews | Reddit | Both |
|---|---:|---:|---:|---:|
| Experience | 25 | 25 | 2 | 2 |
| Adoption | 17 | 17 | 6 | 6 |
| Spec content | 29 | 29 | 14 | 14 |
| Spec structure | 27 | 27 | 10 | 10 |
| Spec workflow | 61 | 60 | 32 | 31 |
| Spec evaluation | 37 | 37 | 11 | 11 |
| Spec maintenance | 29 | 29 | 6 | 6 |
| Tooling | 32 | 31 | 17 | 16 |
| Collaboration | 13 | 13 | 1 | 1 |
| Benefit | 26 | 24 | 17 | 15 |
| Challenge | 64 | 53 | 32 | 21 |
| Learning curve | 13 | 13 | 3 | 3 |
| Agentic SE | 30 | 30 | 14 | 14 |
| SDD perception | 18 | 18 | 9 | 9 |
| Other | 6 | 6 | 0 | 0 |
| **Total** | **427** | **412** | **174** | **159** |

## Experience

| Low-level code | Participants | Reddit records |
|---|---|---|
| open-source contributor or maintainer | **P1**, **P2**, P3, P5, **P6**, P7, P8, P10, **P11**, P17, P19 | – |
| industry or enterprise software | P4, **P6**, **P9**, P10, **P11**, P12, P16, P18, P19, **P21** | – |
| SDD used solo | **P1**, **P2**, P7, P8, **P11**, P15, P17, P18, **P21** | – |
| SDD used in a team with non-developer roles | P4, **P6**, **P9**, P10, P12, **P13**, P16, P19 | – |
| works in teams | **P2**, P3, P5, **P6**, P10, **P11**, P12, **P13** | – |
| heavy use of AI coding agents | **P2**, **P6**, P7, P8, P10, P19 | – |
| less than 10 years of experience | P4, P5, P10, P14, P16, **P20** | – |
| domain-specific background | **P1**, P8, **P13**, P16, P17 | – |
| full-stack or polyglot development | P5, P8, P10, P12, P19 | – |
| large-scale codebases | **P6**, P8, **P9**, P14, **P21** | – |
| solo developer | **P2**, P7, P8, P17, P19 | – |
| pays for tokens personally | **P1**, P3, P15, P18 | R99 |
| 20-29 years of experience | P3, P8, **P11**, P12 | – |
| evolution of AI tool usage | **P1**, P4, P5, P16 | – |
| type and scope of projects | **P2**, P3, P15, P18 | – |
| non-developer or non-traditional background | **P1**, P17, P18 | R98 |
| backend development | P4, **P13**, P16 | – |
| organization tracks token spend or ROI | P4, P10, P16 | – |
| personal side projects | P15, P19, **P21** | – |
| SDD used in a developer-only team | P3, P5, P14 | – |
| startup or founder | P14, P18, **P20** | – |
| 10-19 years of experience | **P13**, P19 | – |
| 30+ years of experience | **P6**, P15 | – |
| mobile development | **P13**, P19 | – |
| requirements engineering or traditional SDLC background | **P6**, P12 | – |

## Adoption

| Low-level code | Participants | Reddit records |
|---|---|---|
| motivation: scaling beyond vibe coding | **P2**, P5, **P9**, P15, P18, **P20**, **P21** | R34 |
| introduced by an individual champion | P3, P4, P5, **P6**, **P9**, **P13**, **P21** | – |
| motivation: correctness and quality | **P1**, **P6**, P12, P15, P19 | R38, R92 |
| motivation: structure and control for agents | P8, P10, **P11**, **P13**, P17 | R38 |
| motivation: team coordination | **P2**, P3, P10, P16, **P20** | – |
| motivation: agent context and memory limits | P7, **P9**, P10, **P21** | R38, R39, R45, R59, R95 |
| arrived at SDD organically | **P1**, P3, **P13**, P17 | R43, R72, R86, R87 |
| adopted as an organizational process | P10, P12, P16, P19 | – |
| discovered through community, tools, or content | P4, P17, P19 | – |
| belief in value of SDD | P3, P5 | R66, R92 |
| fits an existing formal process | P10, P12 | – |
| motivation: natural integration with SDLC | P3, P12 | – |
| used personally but not organizationally | P18, **P21** | – |
| abandoned or re-adopted SDD | P19 | – |
| motivation: speed and productivity | P14 | – |
| requires team or organizational shift | **P21** | – |
| skepticism about SDD maturity | P3 | – |

## Spec content

| Low-level code | Participants | Reddit records |
|---|---|---|
| goals, problem statement, and intent (what and why) | **P1**, P3, P4, P5, P8, **P9**, P10, **P11**, P15, P17, P19, **P21** | R15, R31, R45, R98 |
| design and architecture | **P1**, P4, P5, **P6**, P7, P8, **P9**, P12, P15, P16 | R11, R31, R98 |
| implementation detail included | P7, P12, **P13**, P14, P15, P16, P18, P19, **P21** | – |
| tasks and plans | P4, P5, P7, **P9**, P10, **P11**, P12, **P21** | R3, R61, R80 |
| implementation detail kept out of spec | **P1**, **P2**, P3, **P6**, **P9**, **P11**, P17, **P20** | R91 |
| verification and test plan | P3, P8, P10, P14, P15, P16, P19, **P21** | – |
| constraints and guardrails | **P1**, P8, P10, **P11**, P15, **P21** | R3, R20, R34, R42, R45, R92 |
| implementation approach | P4, P7, P10, P14, P19, **P21** | – |
| requirements and user stories | **P6**, **P9**, P12, P14, P16 | R15, R31, R37, R93, R98 |
| domain knowledge and coding conventions | P4, P8, **P11**, **P13**, P16 | R3, R31, R62 |
| acceptance criteria | P4, **P6**, **P9**, P19, **P21** | – |
| what vs. how separation depends on context | P4, P5, **P6**, P8, P15 | – |
| business context | **P6**, **P9**, P10, P17 | R11, R37 |
| technical details (stack, data structures, algorithms) | **P11**, **P13**, P15, P18 | R37, R93 |
| interface and API definitions | **P2**, **P11**, P16, P19 | R93 |
| content varies by project, team, or task | P5, **P9**, **P11**, **P20** | – |
| implementation detail included selectively | P4, P5, P8, P10 | – |
| trade-offs and design decisions | **P1**, P4, P8, P10 | – |
| edge cases and scenarios | **P6**, P17, P19 | R34 |
| open questions | **P1**, P8 | R62 |
| diagrams | **P6**, P10 | – |
| non-functional requirements | **P6**, P16 | – |
| separates requirements (what) from implementation (how) | **P6**, **P9** | – |
| avoid overspecification | P15 | R98 |
| decision history and failed experiments | **P1** | R57 |
| code examples | P8 | – |
| out of scope and non-goals | P4 | – |
| reference manuals for unfamiliar libraries or languages | **P1** | – |
| use cases with flows and conditions | **P6** | – |

## Spec structure

| Low-level code | Participants | Reddit records |
|---|---|---|
| hierarchical decomposition (e.g., PRD or epic, spec, tasks) | **P1**, **P2**, P3, P4, P5, **P6**, P7, P8, **P9**, P10, **P11**, P12, **P13**, P15, P16, P18, P19, **P20**, **P21** | R11, R19, R53, R92 |
| specs linked to each other and to code | **P2**, P4, P5, **P6**, P8, **P9**, **P11**, **P13**, P14, P15, P16, P18, **P20** | R59, R66 |
| specs scoped to individual changes | P4, P5, P8, P10, **P11**, P12, **P13**, P15, P16, P17, P18, P19, **P21** | – |
| tool-defined template | P4, P5, P8, P10, **P11**, P12, **P13**, P15, **P20** | – |
| specs not linked to each other or to code | **P1**, P3, P7, P10, P12, P17, P19, **P21** | – |
| fixed template or schema for spec body | **P2**, **P6**, **P9**, P16, P17, P18, P19 | – |
| specs scoped to system capabilities or subsystems | **P1**, **P2**, P3, **P6**, P7, P14, **P20** | – |
| free-form markdown | **P1**, P3, P7, P14, **P21** | R2 |
| format not important | P3, **P9**, **P11**, P18, **P21** | – |
| separate documents for requirements, design, and tasks | P8, **P9**, P15, **P20** | R2 |
| structure matters for agent reliability | **P2**, **P6**, P17, P19 | R78 |
| implementation detail in separate plan or design artifact | **P1**, **P9**, **P11**, **P20** | – |
| spec organization in folders or by feature | **P1**, P4, P8, P14 | – |
| markdown format | P7, P14, P19 | R95 |
| modular specs scoped to one subject | **P2**, P3 | R66 |
| separate views for humans and agents | P10, **P20** | – |
| spec deltas separating current state from changes | P5, **P20** | – |
| structured notation (Gherkin, EARS, given-when-then) | **P9**, P17 | – |
| structured notation for acceptance tests (outside the spec) | P12, **P21** | – |
| concise specs with size limits | **P2** | R61 |
| issues or tickets as specs | P17 | R54 |
| no standard structure yet | P19 | R40 |
| organization unimportant when used only to clarify intent | **P9** | – |
| reusable spec skeleton | P19 | – |
| scepticism about markdown | P3 | – |
| unambiguous and consistent terminology | P16 | – |
| use-case templates | **P6** | – |

## Spec workflow

| Low-level code | Participants | Reddit records |
|---|---|---|
| AI-authored specs | **P1**, **P2**, P3, P4, P5, **P6**, P7, P8, **P11**, P12, **P13**, P14, P15, P16, P17, P18, P19, **P21** | – |
| spec source: conversation or research with AI | **P1**, P3, P5, P7, P8, **P11**, P14, P15, P17, P18, P19, **P21** | R5, R18, R19, R43 |
| iterative spec refinement | **P1**, **P2**, **P6**, P8, **P9**, P12, P14, P15, P16, P18, P19, **P20** | R51 |
| spec-gated autonomous workflow | **P2**, P3, P7, P8, **P9**, **P11**, P14, P17, P19, **P21** | R39, R59, R63, R70, R74, R88, R90 |
| SDD for brownfield projects | **P2**, P4, **P6**, P7, P10, P14, P17, **P21** | R20, R25, R28, R62 |
| SDD use decided by task size or complexity | P4, P5, P10, **P11**, P12, **P13**, P14, P19 | R81, R92 |
| research or exploration before spec | **P1**, P4, P8, **P9**, P15, P18, P19, **P20** | – |
| human-gated per-change workflow | P4, P5, P10, P12, **P13**, P15, P16 | R11 |
| spec refined through implementation | **P1**, **P2**, **P6**, **P9**, **P13**, **P20**, **P21** | R54 |
| SDD use decided by risk or uncertainty | **P2**, P3, **P9**, P15, P17, **P20**, **P21** | – |
| no SDD for small tasks, bugs, or one-offs | P4, P5, P10, P12, **P13**, P19 | R4, R20, R33, R41, R42, R44, R86, R89, R91 |
| task decomposition and orchestration | P4, **P6**, P7, **P11**, P18, **P21** | R9, R32, R39, R45, R68, R88, R89, R93 |
| test-first development (TDD or ATDD) | **P2**, P4, P7, P14, P17, **P21** | R48, R62, R92, R98 |
| spec source: upstream requirements artifacts | P4, **P6**, **P9**, P10, P12, P16 | R20, R62 |
| workflow depends on organizational context and domain | **P6**, P8, P10, P16, **P20**, **P21** | – |
| agent-led elicitation via clarifying questions | P4, P7, P14, **P20**, **P21** | R19, R43, R45, R54, R61, R88, R89, R93 |
| separate agents for authoring, implementation, and review | **P2**, P4, P5, P10, P17 | R11, R22, R89, R90, R98 |
| SDD use depends on stakes, risk, or trust | **P9**, P15, P17, **P20**, **P21** | R41 |
| vibe coding for exploration and prototypes | **P2**, P3, **P9**, P12, P17 | R93 |
| reverse-engineering specs from existing code | **P2**, **P6**, P8, P10, **P21** | – |
| spec refined before implementation | P5, **P11**, P12, P16, P19 | – |
| SDD for greenfield projects | P5, P7, P10, P16 | R14, R79, R89 |
| integration with issue trackers | P5, P12, P16, P17 | R12 |
| fresh context per task or session | **P2**, P4, P10 | R23, R59, R61, R62, R68, R82, R94 |
| SDD for large or complex work | P5, P10, P14 | R34, R39, R76, R86, R89, R92 |
| human-authored specs | P3, P10, P14 | R19, R21 |
| system-level design-first workflow | **P1**, **P6**, P18 | R92 |
| custom or adapted workflow | P4, **P6**, P7 | – |
| expensive model plans, cheaper model implements | P3, P7, P18 | – |
| multi-model or adversarial spec creation | **P1**, P3, P4 | – |
| parallel implementation | P4, **P6**, **P21** | – |
| workflow choice driven by personal preference or instinct | P8, P10, **P20** | – |
| agent produces a plan before implementation | P14, P19 | R6, R45, R93 |
| requirements, design, and tasks phases | **P9**, P10 | R45, R76, R98 |
| human approval before implementation | **P2**, **P20** | R45, R76 |
| model tiering (strong models plan, cheaper models implement) | P7, P18 | R29, R76 |
| PRD-to-spec-to-plan pipeline | P4, P5 | R18, R80 |
| SDD for features and refactoring | P4, **P13** | R92 |
| always follows SDD workflow | **P6**, P7 | – |
| bugs fixed by direct prompting | P7, P8 | – |
| CI/CD and programmatic gating | **P2**, P17 | – |
| spec as change request over existing code | **P11**, P16 | – |
| team roles in spec creation | **P6**, P16 | – |
| step-by-step implementation with checkpoints | **P13** | R20, R42, R43, R62, R92 |
| design-heavy upfront, code later | **P1** | R31, R70 |
| SDD use depends on clarity or maturity of intent | **P2** | R74, R84 |
| task decomposition and orchestration using skills | P4 | R90 |
| follows tool defaults | P5 | – |
| human acts as orchestrator | P18 | – |
| human control over task progression | **P6** | – |
| implementation deferred until interfaces are agreed | **P2** | – |
| low threshold for using SDD | P8 | – |
| PRD-to-spec-to-plan pipeline: cross-repo spec authoring | P4 | – |
| prototype first, spec afterwards | **P21** | – |
| SDD use driven by team or organizational policy | P19 | – |
| specs fed to agent incrementally | P18 | – |
| stable use-case and domain-model approach | **P6** | – |
| starts from idea or brain dump | P8 | – |
| tests written after implementation (not TDD) | P5 | – |
| vibe coding for debugging and brainstorming | P12 | – |
| human implements code from the spec | – | R35 |

## Spec evaluation

| Low-level code | Participants | Reddit records |
|---|---|---|
| end-to-end or acceptance tests | P3, P4, **P6**, **P9**, P12, **P13**, P14, P16, P17, P18, P19, **P21** | – |
| human-anchored verification (acceptance criteria or human-defined tests) | **P1**, P4, P5, **P6**, **P9**, P12, **P13**, P16, P17, P19, **P21** | – |
| tests verify code against spec | **P1**, **P2**, P4, **P6**, P8, **P11**, P14, P15, P17, **P21** | R26, R61, R78 |
| manual spec review | **P2**, P5, **P6**, P8, P10, P12, **P13**, P14, P16, **P20** | R62, R92 |
| verification left to agents | **P2**, P3, P7, P8, P10, **P11**, P14, P15, P18, **P20** | – |
| multi-agent adversarial review | **P1**, **P2**, P3, P4, P8, **P9**, P17, **P21** | R50, R76 |
| verification is hard or unsolved | **P1**, P3, P8, P10, P14, P16, P18, **P20** | R44, R77 |
| full human spec review | **P2**, **P6**, **P11**, P12, **P13**, P16, P19 | – |
| partial or cursory spec reading | P4, P5, P7, P8, P14, P15, **P20** | – |
| manual code review | P5, P12, **P13**, P15, P19, **P21** | R18, R31, R57, R93 |
| agent-based code review | **P2**, P5, **P6**, P12, P14, P19 | R12, R46, R76 |
| deterministic checks (CI, linters, static analysis) | **P2**, P3, P5, P8, P12, **P21** | R44, R55 |
| requirement-code-test traceability | **P6**, **P9**, P18, P19, **P20** | R2, R3, R41, R45, R98 |
| AI-generated tests | P5, P7, P12, P17, **P21** | – |
| humans define behavior-level tests | P4, **P9**, P12, P17, **P21** | – |
| spec review primarily delegated to agents | P3, **P9**, P10, P17, P18 | – |
| team or peer spec review | **P6**, P10, P16, P19, **P20** | – |
| concerns about test quality | P3, P7, **P11**, **P20** | – |
| spec defects discovered during implementation | **P6**, P7, P8, **P13** | – |
| agent-based spec review | P3, P12, **P13** | R43 |
| criteria for a good spec | **P9**, P10, P19 | – |
| humans review AI-written tests | P5, **P6**, P12 | – |
| mainly unit tests | **P2**, P7, P15 | – |
| independent reviewer context | P17, **P21** | R85 |
| no systematic evaluation | P7, **P13** | – |
| spec quality judged intuitively | **P1**, **P2** | – |
| unable to judge spec quality | P17 | R48 |
| dataset or benchmark-based evaluation | P19 | – |
| formal verification discussed | **P20** | – |
| human-led questioning of the agent about specs | P17 | – |
| limited or no manual test review | P7 | – |
| no dedicated traceability or quality eval | P5 | – |
| review of test coverage and quality gates | P5 | – |
| separate testing team | P16 | – |
| task-list completion checks | P5 | – |
| tests added to prevent recurring bugs | P7 | – |
| visual or UI-based evaluation | P18 | – |

## Spec maintenance

| Low-level code | Participants | Reddit records |
|---|---|---|
| living spec kept current | **P1**, **P2**, P3, **P6**, P8, **P9**, P16, P18, P19, **P20** | – |
| specs as historical record and provenance | P5, P7, P8, **P9**, P10, **P11**, P18, P19, **P20** | – |
| specs committed with code | P4, P5, P8, **P9**, P10, **P11**, **P13** | R76, R87, R91 |
| drift detection and checks | **P2**, **P6**, P8, P10, **P11**, P12, P14 | R46 |
| specs never deleted | P4, P5, **P6**, P7, P8, **P13**, P19 | – |
| specs kept as accumulated record | P4, P5, P7, P10, **P11**, **P13** | – |
| specs updated alongside changes | **P1**, P3, P8, P18 | R3 |
| spec or repository bloat | P8, **P9**, P10, **P11** | – |
| sync and archive specs after implementation | P8, **P13**, P18, **P20** | – |
| spec as source of truth | **P6**, **P9**, P19 | R44, R45, R50 |
| specs temporary, discarded after implementation | P12, P14, **P21** | R54, R61, R96 |
| consolidate or refactor specs | P3, P17, P18 | – |
| specs discarded after implementation | P12, P14, **P21** | – |
| specs not updated after implementation | P4, **P13**, **P21** | – |
| code as source of truth | **P11**, **P21** | – |
| spec versioning | P16, P19 | – |
| specs not committed | P4, P14 | – |
| spec status lifecycle metadata | **P2** | R73 |
| acceptance tests as the durable artifact | **P21** | – |
| centralized spec repository | P16 | – |
| drift checks cost more than they catch | **P6** | – |
| future intent to retain specs | P12 | – |
| living docs maintained instead of specs | P14 | – |
| new specs instead of modifying existing ones | P4 | – |
| pushing all artifacts unnecessary | P3 | – |
| requirements kept upstream in tickets or requirement tools | P12 | – |
| specs retained after implementation | **P20** | – |
| task lists disposable while requirements persist | **P9** | – |
| update behavior unknown or unverified | P17 | – |

## Tooling

| Low-level code | Participants | Reddit records |
|---|---|---|
| customization level: builds own tool or workflow | **P1**, **P2**, P3, **P6**, **P9**, **P11**, **P13**, P14, P18, **P20**, **P21** | R69, R72, R83 |
| built own SDD tool or framework | **P2**, P8, **P11**, **P13**, P14, P19, **P20**, **P21** | R20, R48, R49, R50, R54, R55, R56, R59, R61, R63, R65, R66, R67, R73, R76, R90, R94 |
| customization level: extends an existing tool | P4, P7, P8, P10, P12, P16, P17, P19 | R2, R74, R82 |
| uses OpenSpec | P5, P7, P8, **P9**, P10, **P13**, P15, **P20** | R1, R56, R79 |
| customizing SDD tools | **P6**, **P9**, P10, **P13**, P19, **P20**, **P21** | R2, R22, R27, R81 |
| tool choice driven by flexibility and lightness | P7, P8, **P9**, P15, P19, **P20** | R2, R16, R79, R81, R95 |
| need: integration with other artifacts and tools | P5, **P6**, P8, P10, **P11**, **P20** | – |
| switched to a lighter or more customizable tool | P7, P8, **P11**, **P13**, P15, P19 | – |
| customizes for organizational fit | P4, **P6**, P10, P12, P19 | – |
| existing tools did not match their approach | **P2**, **P9**, **P11**, **P13**, **P20** | – |
| uses Spec Kit | **P2**, P10, **P11**, P16 | R6, R13, R42, R43, R62, R72, R91 |
| need: evals and benchmarks | P10, P16, **P20** | R71 |
| tools embody different philosophies | P8, **P9**, **P20** | R40 |
| customizes for personal workflow fit | P7, P17, **P21** | – |
| uses Superpowers | P4, P7, P19 | – |
| uses Kiro | P12, P19 | R76 |
| customization level: uses defaults | P5, P15 | – |
| need: better spec review interfaces | P10, **P20** | – |
| need: links and dependency maps between specs | P7, P10 | – |
| need: visualization of specs | P7, P10 | – |
| switched SDD tools without abandoning SDD | P7, **P9** | – |
| uses BMAD | P17 | R5, R12, R15, R59, R68, R81, R88 |
| preference for open, inspectable tools | P19 | R6, R62, R79, R87 |
| need: progress tracking across work | **P21** | R59, R74, R90 |
| need: traceability and provenance | **P20** | R73 |
| prioritize intended outcome over tool choice | **P9** | R53 |
| uses Traycer | P18 | R19 |
| interested in Superpowers (not yet used) | P5 | – |
| need: higher-level planning and orchestration above specs | P8 | – |
| preference for IDE integration and review convenience | **P13** | – |
| used OpenSpec but abandoned | P7 | – |
| compares or surveys SDD tools | – | R2, R3, R4, R17, R39, R40, R45, R54, R62, R67, R70, R78 |

## Collaboration

| Low-level code | Participants | Reddit records |
|---|---|---|
| collaboration as a goal rather than an observed outcome | **P1**, **P2**, P3, **P9**, **P11**, **P20**, **P21** | – |
| team alignment on workflow | **P2**, **P6**, P10, **P11**, P16, P19 | – |
| specs reviewed before code | P5, P10, **P13**, **P20** | R41 |
| modest team benefit, spec as shared review artifact | P4, P5, **P13**, P19 | – |
| not applicable, SDD practiced solo | P7, P8, P15, P18 | – |
| access for non-technical stakeholders | **P9**, **P20**, **P21** | – |
| little or no change in human collaboration | P12, P14, P17 | – |
| shared understanding across roles | **P6**, P10, P16 | – |
| shifting roles (PM, BA, architect) | **P6**, P10, P16 | – |
| spec as team communication artifact | P5, **P13**, P17 | – |
| no change in team collaboration | P12, P17 | – |
| attracting and onboarding contributors | **P1** | – |
| limited change in team collaboration | P14 | – |

## Benefit

| Low-level code | Participants | Reddit records |
|---|---|---|
| more reliable agent work | **P1**, **P2**, P4, P5, **P6**, P7, P8, **P9**, P10, **P11**, **P13**, P14, P15, P16, P17, P19, **P20**, **P21** | R6, R42, R45, R76, R83, R89, R91 |
| faster delivery and productivity | **P6**, P8, P10, **P11**, P14, P16, P19 | R59, R67, R84 |
| reduced tokens and rework | P4, **P9**, **P11**, **P13**, P14, P16, P17 | R18, R45 |
| reduced review and cognitive effort | **P2**, P10, **P11**, **P13**, **P20** | R91, R95 |
| agent-written spec exposes gaps in own intent | P7, **P11**, P14, P17, **P20** | – |
| better context management | **P1**, P4, **P9**, **P21** | R39, R79, R91 |
| clarity of thinking and intent | **P1**, **P9**, P18, P19 | R34, R41 |
| control and alignment of agents | P8, **P13**, P19 | R41, R83 |
| handles complex changes and larger projects | **P2**, P5, P15 | R78, R80 |
| long-horizon or unattended agent work | P10, P14, P19 | R20, R70 |
| improved code quality | P5, P14, P17 | R91 |
| shared understanding | P5, P16, P17 | R91 |
| documentation and project knowledge | P4, **P6**, P10 | – |
| sustained velocity as the codebase grows | **P2**, **P6**, **P9** | – |
| enables parallel work | P4, P14 | R91 |
| improved output quality | **P6**, P10 | – |
| reduced communication overhead | P10, P16 | – |
| traceability and accountability | P10 | R41, R44, R45, R85 |
| uncovers tacit requirements | P18 | R41, R77 |
| less debugging | P7 | R84 |
| benefits not attributable to SDD | P12 | – |
| bridges business and developers | **P6** | – |
| onboarding | P10 | – |
| trust and reassurance | P12 | – |
| specs portable across agents and tools | – | R42, R95 |
| lowers the entry barrier for newcomers | – | R77 |

## Challenge

| Low-level code | Participants | Reddit records |
|---|---|---|
| token and model costs | **P1**, P3, P5, **P6**, P7, P8, P10, **P13**, P14, P15, P16, P17, P18, P19 | R1, R10, R36, R41, R54, R55, R69, R77, R79, R82, R92, R99 |
| spec-code drift | **P2**, P5, **P6**, P7, P8, P10, **P11**, P12, **P13**, P14, P16, P18, P19, **P21** | R42, R46, R53, R55 |
| time overhead | **P1**, P3, P4, **P6**, P10, **P13**, P16, P17, P18, **P21** | R4, R18, R41, R48, R62, R68, R74, R82, R86, R89 |
| drift type: agent deviates during implementation | P5, **P6**, P7, P8, P16, P17, P18, P19 | – |
| drift type: spec goes stale as code evolves | **P2**, P8, P10, **P11**, P12, P14, **P21** | R73 |
| underspecification and unknown unknowns | **P1**, **P6**, P8, **P11**, P14, P18 | R48, R82 |
| increased review load and large PRs | P4, P8, P10, **P11**, P12, P14 | – |
| difficulties as project size grows | P3, P4, P14, P15, P18 | R4, R55, R84 |
| organizational adoption inertia | P5, **P6**, **P9**, P19, **P21** | – |
| spec corpus grows like a codebase | P4, P10, **P11**, P17, P18 | – |
| tool rigidity or heaviness | **P2**, P7, P19, **P20** | R16, R24, R25, R32, R54, R67, R69, R74, R79, R86 |
| cross-spec dependencies and complex features | **P2**, P4, P10, P18 | R84 |
| planning consumes most tokens | P3, P10, P18, P19 | – |
| maintaining specs | P3, P5, P19 | R20, R73 |
| cognitive load shifted to spec authors | **P6**, P10, P16 | R82 |
| agents do not follow or skip parts of spec | P16, P17, P18 | – |
| model limitations (hallucination, overreach, assumptions) | P5, P10, P17 | – |
| reading and reviewing long specs | P3, P4, P18 | – |
| difficult for brownfield projects | P10, P16 | R14, R20, R42, R79 |
| articulating tacit intent | **P6**, P10 | R45, R54 |
| limits of specifying far ahead | **P20**, **P21** | R51, R54 |
| rapid change in tools and practices | **P6**, P10 | R8, R52 |
| long or bloated specs | P3, P10 | R33 |
| adoption barrier: fear of job loss or role change | **P6**, P19 | – |
| adoption barrier: lack of evidence to convince others | **P6**, P10 | – |
| balancing spec detail and agent freedom | P10, P15 | – |
| drift cause: incomplete spec | P14, **P21** | – |
| drift cause: model or harness | P5, P19 | – |
| drift cause: own instructions or context | P8, P17 | – |
| few challenges attributed to SDD | **P11**, P17 | – |
| human attention is the bottleneck | P8, P14 | – |
| insufficient context about existing system | P10, P16 | – |
| lack of evals and metrics for workflows | P10, **P11** | – |
| spec correctness hard to evaluate | P8, P10 | – |
| tracking progress across parallel work | P14, **P21** | – |
| verification debt | P14, **P20** | – |
| output varies across models and harnesses | P19 | R1, R52, R56, R71, R86 |
| adoption barrier: technical setup and skills | P5 | R91 |
| agent orchestration over long specs | P3 | R54 |
| agent-induced technical debt | P3 | R57 |
| loss of understanding of or trust in the system | P3 | R57 |
| volatile or uncertain requirements | P16 | R20 |
| adoption barrier: parts of the spec seen as not valuable | **P20** | – |
| AI not accountable | P18 | – |
| AI-written specs hard for humans to understand | P3 | – |
| balancing spec detail and token consumption | P3 | – |
| drift cause: specs not linked to each other | **P2** | – |
| insufficient stakeholder involvement in adoption | **P6** | – |
| no problems with excessive spec detail reported | P5 | – |
| overspecification | P15 | – |
| SDD sustainability long term | P3 | – |
| skepticism about agent maturity | P3 | – |
| tracking progress across sequential work | P18 | – |
| choosing among SDD tools | – | R38, R40, R47 |
| erosion of developer skills and ability to supervise agents | – | R35, R57 |
| no clear improvement over direct prompting | – | R75, R82 |
| no measurable improvement in code quality | – | R41, R82 |
| tools assume a single team and repository | – | R58, R60 |
| generated artifacts vary across runs | – | R82 |
| natural-language specs open to interpretation | – | R54 |
| requirements change across generated artifacts | – | R82 |
| tools cover design and implementation but not setup or verification | – | R78 |
| unclear when SDD is worth using | – | R91 |
| user-interface work hard to specify in text | – | R91 |

## Learning curve

| Low-level code | Participants | Reddit records |
|---|---|---|
| learned by doing and experimentation | **P1**, **P9**, P10, P12, P15, P19, **P21** | R39 |
| practice evolved over time | P3, **P6**, P7, P8 | – |
| advice for newcomers | **P1**, P4, P14 | R77 |
| steep learning curve | P5, P12, P15 | – |
| depends on requirements engineering background | **P6**, P12 | – |
| education and training needs | P8, **P13** | – |
| learned through community resources | P4, P17 | – |
| learning what a good spec looks like | P10, P14 | – |
| low learning curve | P4, **P13** | – |
| harder for non-technical users | P5 | R64 |
| practice has not changed | P16 | – |
| prior experience does not transfer | P19 | – |
| requires harness engineering knowledge | P19 | – |

## Agentic SE

| Low-level code | Participants | Reddit records |
|---|---|---|
| agent failure modes (hallucination, shortcuts, overreach) | **P1**, P3, P5, P8, P14, P16, P18, **P21** | R30, R45, R69, R76 |
| model choice by task and cost | **P1**, P3, P8, **P11**, P12, P14, P15, P18 | R9, R42, R65 |
| context engineering and memory files | **P1**, P4, P8, **P9**, P14, P18, P19 | R21, R27, R43, R54, R80, R92 |
| uses multiple models or harnesses | P4, P5, **P6**, P7, **P13**, P14, P19 | R68 |
| shifting human role (architect, reviewer, orchestrator) | P8, **P9**, **P11**, P14, P15, P19, **P21** | – |
| context window limits | **P1**, P3, **P6**, **P11**, P15, P17 | R23, R54, R62, R69, R76, R94, R95 |
| skills and plugins | P4, P7, P8, P15, **P21** | R21, R23, R62, R68, R93 |
| agents cannot be trusted without checks | **P2**, P3, P14, P19, **P21** | R77, R85 |
| limitations of vibe coding | **P2**, **P11**, P15, P19 | R92, R95 |
| local or open models | **P6**, P15, P16, P18 | R6 |
| agents for testing | P4, P12, P14, P17 | – |
| models and tooling improving over time | P5, **P6**, P8, **P21** | – |
| harness matters as much as or more than model | **P6**, P8, P14 | R85 |
| agents write most or all code | P3, P5, P14 | – |
| cost of frontier models | **P6**, P14, P18 | – |
| faster delivery pace and pressure | **P6**, P19, **P21** | – |
| running agents in parallel | P14, **P21** | R32, R39, R61, R90 |
| agents produce hard-to-maintain code | P3, P14 | R41 |
| changing code review practices | **P6**, P14 | – |
| equity and market concentration concerns | **P6**, **P11** | – |
| productivity measurement | P8, P10 | – |
| security and sandboxing of agents | **P1**, **P6** | – |
| human as bottleneck | P8 | R85 |
| preference for CLI or pipeline agents | **P6** | R6 |
| agent reliability limited to spikes | P3 | – |
| agents for research | P4 | – |
| built own general-purpose agent harness | **P1** | – |
| fine-tuning and specialized small models | P18 | – |
| human-agent handover | **P21** | – |
| structured model I/O (YAML or JSON) | P16 | – |

## SDD perception

| Low-level code | Participants | Reddit records |
|---|---|---|
| planning is expensive, implementation cheap | **P1**, P3, **P6**, P10, P16, **P20** | R34 |
| intent must be clear before specifying | **P1**, **P2**, **P9**, P17, **P21** | – |
| spec as memory and context for agents | P3, P7, **P11**, **P20**, **P21** | – |
| relation to traditional RE and waterfall | **P6**, P12, P18, **P20** | R17, R18, R77, R97 |
| spec as intermediate or disposable artifact | P7, **P9**, P14, **P21** | R96 |
| benefits hard to attribute to SDD alone | P8, P12, P14, **P20** | – |
| definition of spec and SDD is ambiguous | **P9**, P14, **P20** | R7 |
| specs help humans as well as agents | **P1**, P10, **P20** | R95 |
| net time saving uncertain | P3, P14, P17 | – |
| SDD is organizational rather than a tool | **P6**, **P9**, P14 | – |
| spec as contract | **P2**, P10, P19 | – |
| speed gains credited to AI rather than SDD | **P6**, P8, P14 | – |
| SDD may be transitional as models improve | **P20**, **P21** | R38, R41, R70, R75 |
| spec as alignment and communication | **P9**, **P20** | R41 |
| value lies in the process of specifying | **P9**, **P20** | R54 |
| code is the spec | **P21** | R55 |
| agentic SDD perceived as recent | P19 | – |
| specs and plans as intermediate or disposable artifact | P3 | – |

## Other

| Low-level code | Participants | Reddit records |
|---|---|---|
| critique of software industry practices | **P1**, **P2**, P8, **P20** | – |
| project-specific technical detail | **P1**, P4, P18 | – |
| research interests beyond SDD | **P1**, P18 | – |
| oss dependence on people and high quality standards | P3 | – |
| personal context | **P1** | – |
| software and language design philosophy | **P1** | – |
