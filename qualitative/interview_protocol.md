# Interview Protocol

**Understanding Impact of Spec-Driven Workflows on Software Development**

Carnegie Mellon University — Software and Societal Systems Department

This is the semi-structured protocol used for all 21 interviews. The protocol has 17 main questions
(Q1–Q17) in four sections. Lines marked ↳ are follow-up probes, which the interviewer used as
needed. Text in square brackets is an instruction to the interviewer.

The research questions (RQs) named in the section goals use the numbering from the time of the
interviews. In the paper, Section B corresponds to RQ1 (spec content) and RQ2 (workflows),
Section C corresponds to RQ4 (challenges), and Section D corresponds to RQ3 (benefits).

---

## Opening Script

*Read this aloud at the start of each session, before starting the recording:*

> "Before we begin, I want to confirm a few things. You have received and reviewed the consent
> information for this study. Do you have any questions before we proceed?"

[Pause for questions.] [Next, ask for recording permission.]

> "Do you agree to your interview being audio recorded?"

[If the person says yes, explain that you will begin the recording and that you will need to
record their consent. If the person says no to audio recording but still intends to participate,
begin the interview without recording.]

[If the response is affirmative:]

> "We will now begin the audio recording and will ask you to confirm that the consent information
> is provided to you, that you agree to participate in the study, and that you agree to have the
> session recorded. By stating your agreement on the recording, you are confirming consent to be
> recorded under Pennsylvania law."

[After beginning recording:]

> "Do you agree to participate in this interview?"
>
> "Can you confirm that you have reviewed the consent information?"
>
> "Do you agree to be audio recorded for this interview?"

[Once the person verbally agrees to the three questions, the interview can begin.]

---

## Section A — Background and Context (~5 min)

*Goal: Establish the participant's professional context, software development experience, and
general relationship with AI coding tools before focusing on SDD. This section warms up the
conversation and provides framing for later responses.*

**Q1. What types of software projects do you typically work on?**
- ↳ Are these open-source or proprietary?
- ↳ Are these mostly solo projects or collaborative?
- ↳ What's the rough scale — lines of code, team size, lifespan of the project?

**Q2. How long have you been contributing to or maintaining open-source projects on GitHub?**
- ↳ Do you maintain any projects that have significant external contributors?
- ↳ What does a typical week of open-source work look like for you?

**Q3. When did you first start using AI coding agents or tools in your work, and how has that
evolved over time?**
- ↳ Which AI tools/agents do you use now?
- ↳ How central are AI tools to your day-to-day workflow at this point?
- ↳ Did your team or project adopt these tools together, or was it an individual decision?

---

## Section B — SDD Workflows in Practice (~30 min)

*Goal: Deeply explore the participant's SDD workflow — what it looks like, how it was adopted, how
specs are created and used, and how it fits into the broader SDLC. This section addresses RQ1.*

### B.1 — Introduction to SDD

**Q4. When did you first encounter the idea of writing specifications or structured documents to
guide your work with AI coding agents?**

*Interviewer note: If the participant is unfamiliar with the term "spec-driven development,"
briefly clarify: "I mean the practice of creating structured, behavior-oriented documents —
sometimes called specs, PRDs, or SPEC.md files — that you use as context when working with AI
coding agents."*

- ↳ Was this something you came up with yourself, or did you encounter it in a community,
  framework, or tool?
- ↳ Do you use a specific term for this practice — spec-driven development, plan mode, structured
  prompting, something else?

**Q5. Can you walk me through what a spec typically contains in your projects?**

*Interviewer note: If they mention a specific framework (BMAD, Kiro, OpenSpec, Speckit, PRD/RFC
templates), ask them to describe it specifically.*

- ↳ Is it written in Markdown, a formal template, natural language, or something else?
- ↳ Does it describe what the system should do (behavior), how it should be built
  (architecture), or both?
- ↳ How long is a typical spec file? Does it contain more than one requirement?
- ↳ Do you have a consistent structure or template you follow, or does it vary by project?

### B.2 — Workflow Integration

*The goal of this section is to understand how specs fit into your overall software development
lifecycle.*

*Interviewer note: If their account is high-level, ask for specifics: "Can you tell me more about
what happened at [step X]?"*

**Q6. Can you walk me through a recent feature or project where you used SDD?**
- ↳ What triggered the decision to use SDD for that particular task?
- ↳ How did you go from an initial idea to a finished spec?
- ↳ How did the AI agent use the spec — did you feed it the whole doc, or sections at a time?

**Q7. At what stage of the software development lifecycle do you write the spec?**
- ↳ Do you write the spec before any code exists, or at some other point?
- ↳ Who writes the spec — just you, or does the team contribute?
- ↳ Does your spec ever feed into other artifacts like issues, pull requests, or documentation?

**Q8. How do you evaluate that the generated code satisfies what the spec described?**
- ↳ Do you write test cases for each spec?
- ↳ How do you evaluate specs describing non-functional requirements?

**Q9. How do you decide when to use SDD versus when to just start coding or prompting directly?**
- ↳ Is there a project size, complexity level, or type of task where SDD makes the most sense for
  you?
- ↳ From your experience, does SDD work better for greenfield or brownfield projects?
- ↳ Is SDD useful for refactoring, feature enhancements, bug fixing, or something else?

### B.3 — Spec Lifecycle and Evolution

**Q10. What happens to the spec after the code is generated? Does it stay relevant, get updated,
or become outdated?**
- ↳ Do you version-control your spec files alongside your code?
- ↳ Is there a point at which a spec is "complete" or can be deleted?
- ↳ Do you update the spec during or after development?

**Q11. Have you noticed your spec-writing practice change over time?**
- ↳ How does it differ now from when you started?
- ↳ Have you developed personal rules or heuristics for what makes a good spec?
- ↳ Have you learned what to leave out of a spec, not just what to include?

---

## Section C — Challenges and Pain Points (~10 min)

*Goal: Surface friction points, failure modes, and unmet needs. Addresses RQ2. Use the Reddit
themes (context drift, token costs, steep learning curves, artifact risks) as a mental checklist
but do not name them to the participant.*

**Q12. What are the biggest challenges or frustrations you've run into with SDD?**
- ↳ Has the AI ever "drifted" away from the spec — started doing something different from what
  you specified?
- ↳ Have you ever had a spec that was too detailed, causing the AI to get confused or go in
  circles?
- ↳ What about the time or cost involved — is token consumption or API cost a concern?
- ↳ How steep was the learning curve when you first adopted SDD?

**Q13. Have there been cases where SDD made things worse, or where the spec caused real
problems?**
- ↳ Can you walk me through what happened?
- ↳ What would you do differently in that situation now?

**Q14. Are there things you wish existed — tools, standards, or practices — that would make your
SDD workflow better?**
- ↳ Is there anything missing in the current tooling ecosystem for SDD?

---

## Section D — Benefits and Outcomes (~10 min)

*Goal: Understand the concrete benefits participants have observed — to productivity, code
quality, team dynamics, or project outcomes. Addresses RQ3.*

**Q15. Overall, what concrete benefits have you seen from adopting SDD in your projects?**

*Interviewer note: Relates to Theme 2 (Core Benefits) from the Reddit analysis. Listen for
mentions of shipping velocity, cognitive load, engineering quality, and maintainability.*

- ↳ Has it changed how fast you ship features?
- ↳ Has it changed the quality of the code that gets generated — fewer bugs, better
  architecture?
- ↳ Has it reduced how much mental effort you have to put into the implementation phase?
- ↳ Have you noticed any impact on maintainability — making the codebase easier to understand or
  change later?

**Q16. Has SDD changed how you collaborate with others — teammates, contributors, or reviewers?**
- ↳ Does the spec serve as a communication tool between people, or is it mainly for the AI?
- ↳ Has it changed how you onboard new contributors to a project?
- ↳ Has it changed what code reviews look like?

**Q17. If you were to recommend SDD to another developer who has never tried it, what would you
tell them?**
- ↳ What would be your top advice for someone getting started?
- ↳ What pitfalls would you warn them about?
- ↳ Is there a type of developer or project for whom you'd say SDD is not a good fit?

---

## Closing Script

*Read aloud to close each session:*

> "Thank you so much for your time today — this has been really valuable. Before I stop the
> recording, is there anything else you'd like to add about your experience with spec-driven
> development that we haven't covered?"

[Pause for response.]

> "Great. I'm going to stop the recording now."

[Stop recording.]

> "Just to follow up: your responses will be kept confidential, and we'll use a pseudonym in any
> write-up. The audio recording will be deleted once we've transcribed and de-identified the
> transcript. You're welcome to withdraw your data at any time by contacting us at
> singhal2@andrew.cmu.edu. We'll send you a copy of today's informational script by email. Thank you again."
