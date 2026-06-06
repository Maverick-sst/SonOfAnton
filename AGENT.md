# AGENT.md — Son Of Anton Implementation Agent

## Mission

You are operating inside the Son Of Anton codebase.

Son Of Anton is a recruiter-facing AI persona representing Mohammed Rehan (Maverick).

The purpose of the system is to allow recruiters to:

* Learn about Rehan
* Explore projects
* Ask technical questions
* Schedule interviews
* Reschedule interviews
* Interact through voice and chat

The system must remain:

* Grounded
* Honest
* Context-aware
* Action-capable

The objective is NOT to build a generic chatbot.

The objective is to build an AI persona backed by real evidence and real-world actions.

---

# PRIMARY OBJECTIVE

Build the Son Of Anton platform while strictly adhering to the architecture.

The architecture is the source of truth.

The agent must never invent architecture.

The agent must never redesign architecture without explicit instruction.

The agent must always implement within the existing architectural boundaries.

---

# REQUIRED READING ORDER

Before performing ANY task:

1. Read son_of_anton_master_doc.md
2. Read son_of_anton_PRD.md to know what to build
3. Read current task instructions
4. Inspect existing files
5. Produce implementation plan
6. Only then generate code

Failure to follow this process is considered a violation.

---

# CORE ARCHITECTURE

The system consists of:

```txt
Voice Interface
Chat Interface

        |
        v

Anton Orchestrator

        |
  -------------------
  |        |        |
  v        v        v

Knowledge Conversation Action
 Layer       Layer    Layer
```

The architecture is already finalized.

Do not redesign it.

---

# KNOWLEDGE LAYER

Responsible for:

* Resume retrieval
* GitHub retrieval
* LinkedIn retrieval
* RAG
* Vector search
* Evidence gathering

Not responsible for:

* Scheduling
* Session state
* Conversation memory

---

# CONVERSATION LAYER

Responsible for:

* Session memory
* Topic tracking
* Reference resolution
* Follow-up understanding

Examples:

```txt
Tell me more about the second project.

Go back to Morph.

What was the first one again?
```

Not responsible for:

* RAG
* Calendar
* Persistence

---

# ACTION LAYER

Responsible for:

* Availability checks
* Interview booking
* Rescheduling
* Cancellation

The Action Layer owns all external actions.

---

# CALENDAR RULE

Google Calendar is the source of truth.

Database is NOT the source of truth.

Database stores:

* Metadata
* Analytics
* Audit information
* Session information

Interview existence is determined by Calendar.

Never reverse this relationship.

---

# KNOWLEDGE RETRIEVAL RULE

Always follow:

```txt
Cache
   ↓
Retriever
   ↓
Vector Store
   ↓
Evidence
```

Only use live GitHub retrieval when:

* Evidence is missing
* Freshness is required
* User explicitly asks for latest work

Do not call external APIs unnecessarily.

---

# GROUNDING RULE

Never invent information.

Never hallucinate.

Never fill missing information with assumptions.

If evidence is unavailable:

```txt
I do not have enough information to answer that.
```

is the correct behavior.

---

# ORCHESTRATION RULE

Anton is an orchestrator.

Anton is NOT:

* A database
* A retriever
* A calendar service

Anton coordinates systems.

Anton does not replace them.

---

# MULTI-INTENT RULE

A single message may trigger multiple tasks.

Example:

```txt
Tell me about Morph and schedule an interview next week.
```

Should become:

```txt
Knowledge Task
+
Scheduling Task
```

Do not assume:

```txt
One Query
=
One Intent
```

---

# ROUTING RULE

Use Hybrid Routing.

```txt
Fast Router
      |
Low Confidence
      |
LLM Router
```

Do not replace routing with pure LLM routing.

Do not replace routing with pure rule routing.

---

# IMPLEMENTATION WORKFLOW

Before writing code:

## Step 1

Understand the task.

## Step 2

Identify affected files.

## Step 3

Identify dependencies.

## Step 4

Produce implementation plan.

## Step 5

Identify assumptions.

## Step 6

Implement.

## Step 7

Explain modifications.

---

# FILE CREATION RULE

Do NOT create files unnecessarily.

Before creating a file:

Ask:

```txt
Can this functionality belong to an existing file?
```

Only create new files when:

* Responsibility is distinct
* Architecture requires separation
* Existing file would become overloaded

---

# API INTEGRATION POLICY

All external integrations must be implemented in two phases.

## Phase 1 — Contract Phase

Create:

* Interfaces
* Schemas
* Service layer
* Mock responses

No API keys required.

No production credentials required.

---

## Phase 2 — Integration Phase

Add:

* Authentication
* API keys
* Real endpoints
* Production validation

---

# SECRET MANAGEMENT RULE

Never hardcode:

```env
OPENAI_API_KEY
VAPI_API_KEY
GOOGLE_API_KEY
GITHUB_TOKEN
DATABASE_URL
```

Always use:

```python
os.getenv(...)
```

or environment configuration.

---

# THIRD PARTY SERVICES

Current approved services:

```txt
OpenAI
Vapi
Twilio
Google Calendar
GitHub
Redis
PostgreSQL
Chroma
LangGraph
LangSmith
```

Do not introduce new infrastructure unless explicitly justified.

---

# OBSERVABILITY RULE

Every critical component must be observable.

Prefer:

* Structured logs
* Traces
* Explicit error handling

Do not swallow exceptions.

---

# TESTING RULE

Every implementation must include:

1. Happy path
2. Failure path
3. Edge cases

Code is not complete until it can be tested.

---

# DO NOT BUILD

Do NOT build:

```txt
Custom WebRTC

Custom Voice Infrastructure

Custom Vector Database

Custom Agent Runtime

Custom Scheduling Platform

Microservices

Kubernetes

Event Buses

Over-Engineered Infrastructure
```

The goal is shipping.

Not infrastructure experimentation.

---

# CURRENT TECHNOLOGY STACK

Frontend:

```txt
Next.js
React
Tailwind
```

Backend:

```txt
FastAPI
Python
```

Agent Runtime:

```txt
LangGraph
```

Voice:

```txt
Vapi (Custom LLM mode, Twilio-imported number)
```

LLM:

```txt
GPT-4o / GPT-4.1
```

Vector Store:

```txt
Chroma
```

Cache:

```txt
Redis
```

Database:

```txt
PostgreSQL
```

Observability:

```txt
LangSmith
```

Deployment:

```txt
Vercel
Render
```

---

# CURRENT PHILOSOPHY

Favor:

```txt
Simple
Reliable
Grounded
Observable
Maintainable
```

Avoid:

```txt
Premature Optimization
Fancy Architecture
Unnecessary Abstractions
Framework Obsession
Scope Creep
```

---

# DEFINITION OF SUCCESS

A recruiter should be able to:

1. Ask questions about Rehan
2. Receive grounded answers
3. Continue follow-up discussions
4. Schedule interviews
5. Reschedule interviews
6. Interact via chat
7. Interact via voice

without noticing architectural complexity.

The system succeeds when it feels natural, truthful, and reliable.

Everything else is secondary.
